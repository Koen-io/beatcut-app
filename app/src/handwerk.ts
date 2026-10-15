// Welke shots zijn met de hand bijgesteld? "Opnieuw regisseren" gooit die
// weg, en dat vraagt om een bevestiging — maar alleen als er iets te
// verliezen valt. Een montage zonder handwerk mag zonder vraag opnieuw.
//
// Een shot telt als handwerk als de engine hem `vast` gezet heeft: dat doet
// `project.shot_zet` bij elke bijstelling (venster, snelheid, kader). De
// clipvoorkeuren moet/nooit tellen níét mee: die overleven een nieuwe regie.

type MetVast = { vast: boolean };

export function telHandwerk(shots: readonly MetVast[]): number {
  return shots.filter((s) => s.vast).length;
}

export function heeftHandwerk(shots: readonly MetVast[]): boolean {
  return telHandwerk(shots) > 0;
}
