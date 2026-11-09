//! Olm double-ratchet bindings for Initiative's direct messages.
//!
//! This crate contains no cryptography of its own. It is an ergonomics and
//! serialisation shim over [`vodozemac`], which is the audited Rust
//! implementation of the Olm and Megolm ratchets — we take only Olm, because
//! direct messages are one-to-one and Megolm exists to make group messaging
//! cheap.
//!
//! **State lives in TypeScript, not here.** Every entry point takes the pickles
//! it needs and hands new ones back, so the caller decides where they are
//! stored and nothing is retained across a call. A pickle is already encrypted
//! by vodozemac under a 32-byte key the caller supplies, which is the only
//! secret the platform layer has to protect.
//!
//! The one exception is [`Verification`], which lives for a single comparison
//! between two of an account's devices and is dropped when it ends. vodozemac
//! cannot pickle it, and nothing about it is worth keeping.
//!
//! One WebAssembly artifact serves the browser and both native apps, because
//! Capacitor runs the same web bundle inside a WebView.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use vodozemac::{
    olm::{Account, AccountPickle, OlmMessage, Session, SessionConfig, SessionPickle},
    sas::{EstablishedSas, Mac, Sas},
    Curve25519PublicKey, Ed25519PublicKey, Ed25519Signature,
};
use wasm_bindgen::prelude::*;

/// A published key, as the directory carries it, signed by the device that
/// published it.
#[derive(Serialize, Deserialize)]
pub struct PublishedKey {
    pub key_id: String,
    pub public_key: String,
    pub signature: String,
}

/// What a device signs to say which account its keys belong to. The server
/// verifies the same bytes (``app.services.platform.dm_transport``).
const DEVICE_TAG: &[u8] = b"initiative-dm-device-v1\0";
/// What a device signs over each one-time key it publishes, and its fallback.
const ONE_TIME_KEY_TAG: &[u8] = b"initiative-dm-otk-v1\0";
const FALLBACK_KEY_TAG: &[u8] = b"initiative-dm-fallback-v1\0";
/// What a device signs over each message it relays while verifying another.
const VERIFICATION_TAG: &[u8] = b"initiative-dm-verification-v1\0";

fn device_bytes(
    user_id: u64,
    identity: &Curve25519PublicKey,
    fingerprint: &Ed25519PublicKey,
) -> Vec<u8> {
    [
        DEVICE_TAG,
        &user_id.to_be_bytes(),
        identity.as_bytes(),
        fingerprint.as_bytes(),
    ]
    .concat()
}

fn key_bytes(key: &Curve25519PublicKey, fallback: bool) -> Vec<u8> {
    let tag = if fallback { FALLBACK_KEY_TAG } else { ONE_TIME_KEY_TAG };
    [tag, key.as_bytes()].concat()
}

fn user_id(value: f64) -> Result<u64, JsError> {
    if value.fract() != 0.0 || value < 1.0 || value > 9_007_199_254_740_991.0 {
        return Err(JsError::new("bad user id"));
    }
    Ok(value as u64)
}

#[derive(Serialize)]
pub struct AccountCreated {
    pub pickle: String,
    pub identity_key: String,
    pub fingerprint_key: String,
}

#[derive(Serialize)]
pub struct KeysGenerated {
    pub pickle: String,
    pub one_time_keys: Vec<PublishedKey>,
    pub fallback_key: Option<PublishedKey>,
}

#[derive(Serialize)]
pub struct OutboundSession {
    pub session_pickle: String,
    pub session_id: String,
}

#[derive(Serialize)]
pub struct InboundSession {
    pub account_pickle: String,
    pub session_pickle: String,
    pub session_id: String,
    pub plaintext: String,
}

#[derive(Serialize)]
pub struct Encrypted {
    pub session_pickle: String,
    pub message_type: u8,
    pub ciphertext: String,
}

#[derive(Serialize)]
pub struct PreKeyInspected {
    pub session_id: String,
    pub identity_key: String,
}

#[derive(Serialize)]
pub struct Decrypted {
    pub session_pickle: String,
    pub plaintext: String,
}

fn pickle_key(encoded: &str) -> Result<[u8; 32], JsError> {
    let raw = base64_decode(encoded)?;
    raw.try_into()
        .map_err(|_| JsError::new("pickle key must be 32 bytes"))
}

fn base64_decode(encoded: &str) -> Result<Vec<u8>, JsError> {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD
        .decode(encoded)
        .map_err(|_| JsError::new("expected base64"))
}

fn base64_encode(raw: &[u8]) -> String {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD.encode(raw)
}

fn load_account(pickle: &str, key: &str) -> Result<Account, JsError> {
    let key = pickle_key(key)?;
    let pickle = AccountPickle::from_encrypted(pickle, &key)
        .map_err(|_| JsError::new("could not read the account key store"))?;
    Ok(Account::from_pickle(pickle))
}

fn save_account(account: &Account, key: &str) -> Result<String, JsError> {
    Ok(account.pickle().encrypt(&pickle_key(key)?))
}

fn load_session(pickle: &str, key: &str) -> Result<Session, JsError> {
    let key = pickle_key(key)?;
    let pickle = SessionPickle::from_encrypted(pickle, &key)
        .map_err(|_| JsError::new("could not read the session key store"))?;
    Ok(Session::from_pickle(pickle))
}

fn save_session(session: &Session, key: &str) -> Result<String, JsError> {
    Ok(session.pickle().encrypt(&pickle_key(key)?))
}

fn published(
    account: &Account,
    keys: HashMap<vodozemac::KeyId, Curve25519PublicKey>,
    fallback: bool,
) -> Vec<PublishedKey> {
    let mut out: Vec<PublishedKey> = keys
        .into_iter()
        .map(|(id, key)| PublishedKey {
            key_id: id.to_base64(),
            public_key: key.to_base64(),
            signature: account.sign(key_bytes(&key, fallback)).to_base64(),
        })
        .collect();
    // A stable order so a caller comparing two runs sees the same list.
    out.sort_by(|a, b| a.key_id.cmp(&b.key_id));
    out
}

fn to_js<T: Serialize>(value: &T) -> Result<JsValue, JsError> {
    serde_wasm_bindgen::to_value(value).map_err(|error| JsError::new(&error.to_string()))
}

/// Generate this device's long-lived identity.
///
/// The private halves exist only inside the returned pickle, which is already
/// encrypted under `key`.
#[wasm_bindgen]
pub fn create_account(key: &str) -> Result<JsValue, JsError> {
    let account = Account::new();
    to_js(&AccountCreated {
        identity_key: account.curve25519_key().to_base64(),
        fingerprint_key: account.ed25519_key().to_base64(),
        pickle: save_account(&account, key)?,
    })
}

/// Top the prekey pool up, and mint a fallback key if asked.
///
/// The fallback key is reusable and is what a sender gets when the pool is
/// drained, so a device that has been quiet for a long time stays reachable.
#[wasm_bindgen]
pub fn generate_keys(
    pickle: &str,
    key: &str,
    count: usize,
    with_fallback: bool,
) -> Result<JsValue, JsError> {
    let mut account = load_account(pickle, key)?;
    account.generate_one_time_keys(count);
    let one_time_keys = published(&account, account.one_time_keys(), false);
    let fallback_key = if with_fallback {
        account.generate_fallback_key();
        published(&account, account.fallback_key(), true).into_iter().next()
    } else {
        None
    };
    // Published means published: the account stops offering them again.
    account.mark_keys_as_published();
    to_js(&KeysGenerated {
        pickle: save_account(&account, key)?,
        one_time_keys,
        fallback_key,
    })
}

/// Sign this device's keys as belonging to `user_id`.
#[wasm_bindgen]
pub fn sign_device(pickle: &str, key: &str, user_id_value: f64) -> Result<String, JsError> {
    let account = load_account(pickle, key)?;
    let bytes = device_bytes(
        user_id(user_id_value)?,
        &account.curve25519_key(),
        &account.ed25519_key(),
    );
    Ok(account.sign(bytes).to_base64())
}

fn verify(fingerprint: &Ed25519PublicKey, message: &[u8], signature: &str) -> bool {
    Ed25519Signature::from_base64(signature)
        .map(|signature| fingerprint.verify(message, &signature).is_ok())
        .unwrap_or(false)
}

/// Whether a directory entry's keys were signed, by its own fingerprint key,
/// as belonging to `user_id`.
#[wasm_bindgen]
pub fn verify_device(
    user_id_value: f64,
    identity_key: &str,
    fingerprint_key: &str,
    signature: &str,
) -> Result<bool, JsError> {
    let identity = Curve25519PublicKey::from_base64(identity_key)
        .map_err(|_| JsError::new("bad identity key"))?;
    let fingerprint = Ed25519PublicKey::from_base64(fingerprint_key)
        .map_err(|_| JsError::new("bad fingerprint key"))?;
    let bytes = device_bytes(user_id(user_id_value)?, &identity, &fingerprint);
    Ok(verify(&fingerprint, &bytes, signature))
}

/// Sign one relayed verification message as this device's.
#[wasm_bindgen]
pub fn sign_verification(pickle: &str, key: &str, message: &str) -> Result<String, JsError> {
    let account = load_account(pickle, key)?;
    Ok(account
        .sign([VERIFICATION_TAG, message.as_bytes()].concat())
        .to_base64())
}

/// Whether a relayed verification message was signed by the device whose
/// fingerprint key the directory lists.
#[wasm_bindgen]
pub fn verify_verification(
    fingerprint_key: &str,
    message: &str,
    signature: &str,
) -> Result<bool, JsError> {
    let fingerprint = Ed25519PublicKey::from_base64(fingerprint_key)
        .map_err(|_| JsError::new("bad fingerprint key"))?;
    Ok(verify(
        &fingerprint,
        &[VERIFICATION_TAG, message.as_bytes()].concat(),
        signature,
    ))
}

/// Open a session with a device, spending a prekey claimed from the directory.
///
/// The prekey's signature must verify against the device's fingerprint key.
#[wasm_bindgen]
pub fn create_outbound_session(
    pickle: &str,
    key: &str,
    their_identity_key: &str,
    their_fingerprint_key: &str,
    their_one_time_key: &str,
    one_time_key_signature: &str,
    fallback: bool,
) -> Result<JsValue, JsError> {
    let account = load_account(pickle, key)?;
    let identity = Curve25519PublicKey::from_base64(their_identity_key)
        .map_err(|_| JsError::new("bad identity key"))?;
    let one_time = Curve25519PublicKey::from_base64(their_one_time_key)
        .map_err(|_| JsError::new("bad one-time key"))?;
    let fingerprint = Ed25519PublicKey::from_base64(their_fingerprint_key)
        .map_err(|_| JsError::new("bad fingerprint key"))?;
    if !verify(&fingerprint, &key_bytes(&one_time, fallback), one_time_key_signature) {
        return Err(JsError::new("one-time key signature does not verify"));
    }
    let session = account.create_outbound_session(SessionConfig::version_2(), identity, one_time);
    to_js(&OutboundSession {
        session_id: session.session_id(),
        session_pickle: save_session(&session, key)?,
    })
}

/// Which session a pre-key message opens, and who sent it, without opening it.
#[wasm_bindgen]
pub fn inspect_prekey(ciphertext: &str) -> Result<JsValue, JsError> {
    let message = OlmMessage::from_parts(0, &base64_decode(ciphertext)?)
        .map_err(|_| JsError::new("not a pre-key message"))?;
    let OlmMessage::PreKey(prekey) = message else {
        return Err(JsError::new("not a pre-key message"));
    };
    to_js(&PreKeyInspected {
        session_id: prekey.session_id(),
        identity_key: prekey.identity_key().to_base64(),
    })
}

/// Answer a pre-key message by deriving the session it describes.
///
/// The account changes too: the prekey it spent is forgotten, so the same
/// message cannot open a second session.
#[wasm_bindgen]
pub fn create_inbound_session(
    pickle: &str,
    key: &str,
    their_identity_key: &str,
    ciphertext: &str,
) -> Result<JsValue, JsError> {
    let mut account = load_account(pickle, key)?;
    let identity = Curve25519PublicKey::from_base64(their_identity_key)
        .map_err(|_| JsError::new("bad identity key"))?;
    let message = OlmMessage::from_parts(0, &base64_decode(ciphertext)?)
        .map_err(|_| JsError::new("not a pre-key message"))?;
    let OlmMessage::PreKey(prekey) = message else {
        return Err(JsError::new("not a pre-key message"));
    };
    let result = account
        .create_inbound_session(identity, &prekey)
        .map_err(|_| JsError::new("could not open the session"))?;
    to_js(&InboundSession {
        account_pickle: save_account(&account, key)?,
        session_id: result.session.session_id(),
        session_pickle: save_session(&result.session, key)?,
        plaintext: String::from_utf8_lossy(&result.plaintext).into_owned(),
    })
}

/// Encrypt one message, advancing the ratchet.
#[wasm_bindgen]
pub fn session_encrypt(pickle: &str, key: &str, plaintext: &str) -> Result<JsValue, JsError> {
    let mut session = load_session(pickle, key)?;
    let message = session.encrypt(plaintext);
    let (message_type, body) = message.to_parts();
    to_js(&Encrypted {
        session_pickle: save_session(&session, key)?,
        message_type: message_type as u8,
        ciphertext: base64_encode(&body),
    })
}

/// Decrypt one message, advancing the ratchet.
#[wasm_bindgen]
pub fn session_decrypt(
    pickle: &str,
    key: &str,
    message_type: u8,
    ciphertext: &str,
) -> Result<JsValue, JsError> {
    let mut session = load_session(pickle, key)?;
    let message = OlmMessage::from_parts(message_type as usize, &base64_decode(ciphertext)?)
        .map_err(|_| JsError::new("unreadable message"))?;
    let plaintext = session
        .decrypt(&message)
        .map_err(|_| JsError::new("could not decrypt"))?;
    to_js(&Decrypted {
        session_pickle: save_session(&session, key)?,
        plaintext: String::from_utf8_lossy(&plaintext).into_owned(),
    })
}

/// How many pictures a verification shows: 24 bits, six to a picture.
const EMOJI_COUNT: usize = 4;

/// One comparison between two of an account's devices.
///
/// Each side makes a fresh key pair, swaps public halves with the other, and
/// both derive the same few pictures from the shared secret. Nothing here is
/// derived from the device's long-lived keys, so every comparison shows
/// different pictures. The long-lived keys are then vouched for with MACs under
/// the same shared secret, once the person says the pictures match.
#[wasm_bindgen]
pub struct Verification {
    public_key: String,
    pending: Option<Sas>,
    established: Option<EstablishedSas>,
}

#[wasm_bindgen]
impl Verification {
    #[wasm_bindgen(constructor)]
    pub fn new() -> Verification {
        let sas = Sas::new();
        Verification {
            public_key: sas.public_key().to_base64(),
            pending: Some(sas),
            established: None,
        }
    }

    /// This side's public key for this comparison.
    #[wasm_bindgen(getter)]
    pub fn public_key(&self) -> String {
        self.public_key.clone()
    }

    /// Derive the shared secret from the other side's public key. Once only.
    pub fn establish(&mut self, their_key: &str) -> Result<(), JsError> {
        let sas = self
            .pending
            .take()
            .ok_or_else(|| JsError::new("already established"))?;
        self.established = Some(
            sas.diffie_hellman_with_raw(their_key)
                .map_err(|_| JsError::new("bad verification key"))?,
        );
        Ok(())
    }

    fn secret(&self) -> Result<&EstablishedSas, JsError> {
        self.established
            .as_ref()
            .ok_or_else(|| JsError::new("not established"))
    }

    /// The pictures to show, as indices into the 64-emoji list.
    pub fn emoji(&self, info: &str) -> Result<Vec<u8>, JsError> {
        Ok(self.secret()?.bytes(info).emoji_indices()[..EMOJI_COUNT].to_vec())
    }

    pub fn mac(&self, input: &str, info: &str) -> Result<String, JsError> {
        Ok(self.secret()?.calculate_mac(input, info).to_base64())
    }

    pub fn verify_mac(&self, input: &str, info: &str, mac: &str) -> Result<bool, JsError> {
        let Ok(tag) = Mac::from_base64(mac) else {
            return Ok(false);
        };
        Ok(self.secret()?.verify_mac(input, info, &tag).is_ok())
    }
}

impl Default for Verification {
    fn default() -> Self {
        Self::new()
    }
}
