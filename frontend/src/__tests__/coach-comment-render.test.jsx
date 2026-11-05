import "@testing-library/jest-dom";
import { render, screen, within } from "@testing-library/react";
import NarrativeWorkoutAnalysis from "@/components/workout/NarrativeWorkoutAnalysis";

const t = (key) => key;
const narrative = {
  language: "en", generation_mode: "deterministic_fallback",
  headline: "C388 HEADLINE", analysis: "C388 ANALYSIS", interpretation: "C388 INTERPRETATION",
  recommendation: "C388 RECOMMENDATION", limitations: ["LIMIT ONE", "LIMIT TWO"],
};
const comment = { status: "generated", language: "en", source: "coach_c396", text: "C396 NATURAL COMMENT" };
const renderIt = (data, props = {}) => render(
  <NarrativeWorkoutAnalysis data={data} lang="en" t={t} detailsAvailable={false} {...props} />,
);

test("accepted C396 comment is the single primary voice", () => {
  renderIt({ narrative_coach_v3: narrative, coach_comment: comment });
  const primary = screen.getByTestId("narrative-coach");
  expect(within(primary).getByText("C396 NATURAL COMMENT")).toBeInTheDocument();
  ["C388 HEADLINE", "C388 ANALYSIS", "C388 INTERPRETATION"].forEach((text) => {
    expect(within(primary).queryByText(text)).not.toBeInTheDocument();
  });
  expect(screen.queryByTestId("narrative-recommendation")).not.toBeInTheDocument();
  expect(screen.queryByText("C388 RECOMMENDATION")).not.toBeInTheDocument();
  // critical limitation stays visible once; the rest and the C388 facts go to details
  expect(screen.getAllByText("LIMIT ONE")).toHaveLength(1);
  expect(within(primary).getByTestId("narrative-limitation")).toHaveTextContent("LIMIT ONE");
  const facts = screen.getByTestId("narrative-deterministic-facts");
  expect(facts).toHaveTextContent("C388 HEADLINE");
  expect(facts).toHaveTextContent("C388 ANALYSIS");
  expect(screen.getByText("LIMIT TWO")).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(1);
});

test.each([
  ["absent", undefined],
  ["fallback", { ...comment, status: "fallback", text: null }],
  ["disabled", { ...comment, status: "disabled", text: null }],
  ["other language", { ...comment, language: "fr" }],
])("C388 rendering is intact when the comment is %s", (_name, value) => {
  renderIt({ narrative_coach_v3: narrative, coach_comment: value });
  const primary = screen.getByTestId("narrative-coach");
  expect(within(primary).getByText("C388 HEADLINE")).toBeInTheDocument();
  expect(within(primary).getByText("C388 ANALYSIS")).toBeInTheDocument();
  expect(within(primary).getByText("C388 INTERPRETATION")).toBeInTheDocument();
  expect(screen.getByTestId("narrative-recommendation")).toHaveTextContent("C388 RECOMMENDATION");
  expect(screen.queryByTestId("coach-session-comment")).not.toBeInTheDocument();
  expect(screen.queryByTestId("narrative-deterministic-facts")).not.toBeInTheDocument();
});
