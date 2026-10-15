// Toetsenbord op de scrubbalk. Pure functie, los van React, zodat
// app/tests/toetsen.test.ts hem zonder browser kan toetsen.
//
//   ← / →         één frame terug / vooruit
//   Shift+← / →   één seconde
//   Home / End    begin / einde
//   J / L         één seconde terug / vooruit (zoals in elke editor)
//   K             (niets hier: K is pauzeren en hoort bij de speelknop)
//
// Geeft de nieuwe tijd, of `null` als de toets niet van ons is — dan mag de
// browser hem gewoon afhandelen.

export function scrubSprong(
  toets: string,
  shift: boolean,
  fps: number,
  duur: number,
  tijd: number,
): number | null {
  if (!(duur > 0)) return null;
  const frame = fps > 0 ? 1 / fps : 1 / 30;
  const klem = (t: number) => Math.min(Math.max(0, t), duur);
  switch (toets) {
    case "ArrowLeft":
      return klem(tijd - (shift ? 1 : frame));
    case "ArrowRight":
      return klem(tijd + (shift ? 1 : frame));
    case "Home":
      return 0;
    case "End":
      return duur;
    case "j":
    case "J":
      return klem(tijd - 1);
    case "l":
    case "L":
      return klem(tijd + 1);
    default:
      return null;
  }
}
