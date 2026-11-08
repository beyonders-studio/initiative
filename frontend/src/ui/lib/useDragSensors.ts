import { KeyboardSensor, MouseSensor, TouchSensor, useSensor, useSensors } from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";

// A mouse drag starts once the pointer has moved a few pixels, so a click is
// still a click.
const MOUSE = { activationConstraint: { distance: 4 } };
// A touch drag starts after a short press and hold, so a swipe still scrolls.
const TOUCH = { activationConstraint: { delay: 200, tolerance: 8 } };
const KEYBOARD = { coordinateGetter: sortableKeyboardCoordinates };

interface DragSensorOptions {
  /** Space or Enter picks the item up and the arrow keys move it. Only where
   *  those keys do nothing else on what is dragged. */
  keyboard?: boolean;
  /** Off where a touch means something else until the person asks to drag. */
  touch?: boolean;
}

/** The sensors every drag in the app starts with, so one drag feels like another. */
export const useDragSensors = ({ keyboard = false, touch = true }: DragSensorOptions = {}) => {
  const mouse = useSensor(MouseSensor, MOUSE);
  const finger = useSensor(TouchSensor, TOUCH);
  const keys = useSensor(KeyboardSensor, KEYBOARD);
  return useSensors(mouse, touch ? finger : null, keyboard ? keys : null);
};
