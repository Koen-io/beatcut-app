// Kleine lijnpictogrammen voor de monteerbalk. Eén stijl (1,6 px lijn,
// ronde uiteinden, `currentColor`) in plaats van een mengsel van Unicode-pijlen
// en een emoji die per systeem anders tekent.

type Naam = "ongedaan" | "opnieuw" | "knip" | "weg" | "links" | "rechts";

const PADEN: Record<Naam, string> = {
  ongedaan: "M5 7H11.5a3.5 3.5 0 0 1 0 7H8M5 7l3-3M5 7l3 3",
  opnieuw: "M13 7H6.5a3.5 3.5 0 0 0 0 7H10M13 7l-3-3M13 7l-3 3",
  knip: "M6 6.5L14 13M6 11.5L14 5M4.5 4.5a1.8 1.8 0 1 0 0.01 0M4.5 13.5a1.8 1.8 0 1 0 0.01 0",
  weg: "M4 5.5h10M7.5 5.5V4h3v1.5M5.5 5.5l.7 8.5h5.6l.7-8.5M8 8v4M10 8v4",
  links: "M10.5 5L6.5 9l4 4",
  rechts: "M7.5 5l4 4-4 4",
};

export default function Ikoon({ naam }: { naam: Naam }) {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        d={PADEN[naam]}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
