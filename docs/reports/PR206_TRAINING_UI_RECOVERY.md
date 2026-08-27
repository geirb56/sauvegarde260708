BASE_SHA = a9714d1fc0b9ce7f938a356650340f81307cfe68
HEAD_SHA = PENDING_COMMIT_SHA

OLD_UI_REFERENCE =
7047ca2cef5026b62e0025de531427fd9d72edd0

CANONICAL_COMPONENT =
TrainingPlanV2.jsx

RECOVERED_VISUAL_PATTERNS =
- Header plan status card with clear goal/week/phase summary
- Today session promoted as primary card
- Weekly session cards with type colors, today emphasis, and clear states
- Dedicated cycle progress card with progress bar
- Collapsible paces section for mobile compaction
- Collapsible full-cycle week list with current-week emphasis

LEGACY_LOGIC_RECOVERED = NO

V2_TODAY = PASS
V2_PACES = PASS
V2_WEEK = PASS
V2_CYCLE = PASS

LEGACY_PLAN_CALLS = 0
LEGACY_FULL_CYCLE_CALLS = 0
LEGACY_METRICS_CALLS = 0

TODAY_SESSION_FIRST = PASS
TODAY_HIGHLIGHTED_IN_WEEK = PASS

SESSION_DETAIL_LINK_SUPPORTED = YES (conditional, if V2 payload includes session_id/workout_id)
SESSION_DETAIL_ROUTE = /sessions/:id OR /workout/:id
SESSION_CLICK_TO_DETAIL = PASS

DONE_PLANNED_REST_STATE_CLEAR = PASS

PACES_COLLAPSIBLE_MOBILE = PASS
TECHNICAL_LABELS_USER_FRIENDLY = PASS

UNKNOWN_DISTANCE_NOT_ZERO = PASS
UNKNOWN_DURATION_NOT_ZERO = PASS
NULL_TSS_NOT_ZERO = PASS

FUTURE_PRESCRIPTION_INVENTED = NO

MAINTENANCE_UI = PASS
FREE_ACCESS_CONTROL = PASS

I18N_EN = PASS
I18N_FR = PASS
I18N_ES = PASS

MOBILE_390 = PASS
DESKTOP = PASS

FRONTEND_FILES_CHANGED =
- frontend/src/pages/TrainingPlanV2.jsx
- frontend/src/lib/i18n.js
- frontend/src/__tests__/training-v2-page.test.jsx

BACKEND_MODIFIED = NO
LOCKFILES_MODIFIED = NO
DEPENDENCIES_MODIFIED = NO

TESTS =
- npm test -- --watchAll=false --runInBand src/__tests__/training-v2-page.test.jsx
- npm test -- --watchAll=false --runInBand src/__tests__/dashboard-training-v2.test.jsx

BLOCKERS =
- None
