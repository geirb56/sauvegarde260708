import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import WorkoutFacts from "@/components/workout/WorkoutFacts";

const t = (key) => key;
const narrative = {
  language: "en", generation_mode: "deterministic_fallback",
  headline: "C388 HEADLINE", analysis: "C388 ANALYSIS", interpretation: "C388 INTERPRETATION",
  recommendation: "C388 RECOMMENDATION", limitations: ["LIMIT ONE", "LIMIT TWO"],
};
const comment = { status: "generated", language: "en", source: "coach_c396", text: "C396 NATURAL COMMENT" };
const facts = {
  version: "v3",
  session_classification: { type: "intervals", evidence: { effort_count: 4, recovery_count: 3 } },
};
const renderIt = (data) => render(<WorkoutFacts data={data} lang="en" t={t} detailsAvailable={false} />);

test.each([
  ["with a coach comment", { narrative_coach_v3: narrative, coach_comment: comment, workout_intelligence_v3: facts }],
  ["without a coach comment", { narrative_coach_v3: narrative, workout_intelligence_v3: facts }],
  ["without narrative", { workout_intelligence_v3: facts }],
])("C416 renders facts only, never narrative prose or the comment (%s)", (_name, data) => {
  renderIt(data);
  const all = document.body.textContent;
  ["C388 HEADLINE", "C388 ANALYSIS", "C388 INTERPRETATION", "C388 RECOMMENDATION", "C396 NATURAL COMMENT"]
    .forEach((text) => expect(all).not.toContain(text));
  expect(screen.queryByTestId("coach-session-comment")).not.toBeInTheDocument();
  expect(screen.getByTestId("workout-evidence")).toHaveTextContent("4");
  expect(screen.getByTestId("workout-evidence")).toHaveTextContent("3");
});

test("keeps the essential narrative limitation visible and no details accordion", () => {
  renderIt({ narrative_coach_v3: narrative, workout_intelligence_v3: facts });
  expect(screen.getByTestId("workout-limitations")).toHaveTextContent("LIMIT ONE");
  expect(screen.queryByTestId("workout-analysis-details")).not.toBeInTheDocument();
});

test("renders nothing without facts or valid narrative", () => {
  const { container } = renderIt({});
  expect(container).toBeEmptyDOMElement();
});
