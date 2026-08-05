# RunIndex — PR N2 : Nettoyage Dashboard autour de ReadinessChart

Périmètre : **frontend uniquement** (`frontend/src/pages/Dashboard.jsx`). Aucun changement backend, aucun changement métier readiness/plan. Zones (55/75), tooltip, tiles, recommendation, `/training/today` et i18n `readinessZones`/`monthlyReadiness` conservés à l'identique.

---

## A. Audit AVANT modification (ACTIF / MORT / INCERTAIN)

Méthode : `grep -oc "\bSYMBOLE\b"` (une seule occurrence ⇒ définition/import seul, pas d'usage JSX) + recherche des balises `<...>` correspondantes + recherche cross-projet.

| # | Symbole | Statut | Preuve |
|---|---------|--------|--------|
| A | `ReadinessChart` | **ACTIF** | Définition + rendu JSX `<ReadinessChart data={history} height={150} />` sous le garde `history.filter(...run_readiness...).length >= 2`. Alimenté par `history.run_readiness`. |
| B | `MiniLineChart` | **MORT** | 1 seule occurrence (définition). Aucun `<MiniLineChart .../>` dans le fichier ni ailleurs. |
| C | `chartData` (`[45, 48, 42, …]`, commentaire « would come from real data ») | **MORT** | 1 seule occurrence (déclaration). Jamais lu/rendu. |
| D | `TrendTooltip` | **MORT** | 1 seule occurrence (définition). Aucune référence (recharts `Tooltip` non monté). |
| E | imports `recharts` : `BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend` | **MORT** (dans Dashboard.jsx) | Chaque symbole = 1 occurrence (import seul), aucune balise JSX. La 2ᵉ occurrence de « Line » est le commentaire `// Mini Line Chart Component`. `recharts` reste utilisé dans `Progress.jsx` (autre fichier, **hors périmètre**, non touché). |
| F | Autres courbes / `BarChart` / `LineChart` rendues dans Dashboard | **Aucune** | Seule courbe rendue = `ReadinessChart`. |
| G | `history.training_load` côté front | **NON LU** | Le front lit `m.training_load` (tuile Charge, métrique du jour), jamais `history.training_load`. Non touché. |
| — | `BarChart2` (lucide) | **ACTIF** — conservé | Utilisé comme icône de la tuile « Charge ». Ne pas confondre avec `BarChart` de recharts. |

Aucun symbole INCERTAIN. Aucune suppression sur symbole non prouvé mort.

---

## B. Fichiers modifiés

- `frontend/src/pages/Dashboard.jsx` (nettoyage)
- `DASHBOARD_CHART_CLEANUP_PR_REPORT.md` (ce rapport)

Non touchés : backend, i18n (`readinessZones`/`monthlyReadiness` conservés), `Progress.jsx`, tests.

---

## C. Liste exacte des suppressions

1. Bloc d'import `recharts` complet (`import { BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";`).
2. Fonction `TrendTooltip(...)` (composant tooltip recharts orphelin).
3. Commentaire + fonction `MiniLineChart(...)` (mini-courbe non branchée).
4. Mock `chartData` : commentaire « Mock data for the chart (would come from real data) » + `const chartData = [45, 48, 42, 50, 55, 58, 62, 68];`.

Conservé strictement identique : le bloc
```jsx
{history.filter((h) => h.run_readiness !== undefined && h.run_readiness !== null).length >= 2 && (
  ...
  <ReadinessChart data={history} height={150} />
  ...
)}
```

---

## D. Empty state

**Non.** Cleanup strict conformément à la consigne (« sinon ne rien ajouter »). Comportement inchangé : quand < 2 points, le bloc courbe ne s'affiche pas (garde existant conservé).

---

## E. Tableau de vérifications

| Vérif | Résultat |
|-------|----------|
| ReadinessChart toujours monté si ≥ 2 points | **PASS** (rendu conservé, garde `>= 2` intact) |
| plus de `chartData` mock | **PASS** (`grep` vide) |
| MiniLineChart : supprimé ou justifié ACTIF | **PASS** (supprimé, prouvé mort) |
| imports recharts : tous utilisés ou retirés | **PASS** (retirés de Dashboard.jsx ; encore utilisés dans Progress.jsx hors périmètre) |
| `grep MiniLineChart / chartData / TrendTooltip / recharts` dans Dashboard.jsx | **PASS** (aucune occurrence) |
| build frontend (`yarn build`) | **PASS** (`Done in 14.05s`, build OK) |
| backend non modifié | **PASS** (0 fichier backend touché) |

---

## F. Risques résiduels

- **Faible.** Suppressions limitées à du code prouvé mort (une seule occurrence chacune). Aucune logique readiness/plan modifiée.
- `recharts` reste dans `package.json` (utilisé par `Progress.jsx`) — volontairement non retiré (hors périmètre).
- PR petite et facilement revertible.

---

## G. Décision

**READY TO MERGE**
