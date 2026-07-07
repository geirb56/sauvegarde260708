# Interactive Training Plan - Implementation Documentation

## Overview

This implementation adds interactive and adaptive features to the CardioCoach training plan, allowing users to provide feedback on sessions and receive dynamically adjusted workouts based on their current fatigue levels.

## Features Implemented

### 1. User Feedback System

**Backend: POST /api/training/feedback**
- Endpoint to store user feedback on training sessions
- Parameters:
  - `date`: ISO date string (YYYY-MM-DD)
  - `workout_id`: Unique identifier for the session
  - `status`: 'done' or 'missed'
- Uses MongoDB `training_feedback` collection
- Prevents duplicates with upsert operation

**Frontend: Feedback Buttons**
- "Réalisé" (Done) and "Manqué" (Missed) buttons
- Visual feedback with color changes (green for done, red for missed)
- Disabled state after submission
- Toast notification on successful save

### 2. Adaptive Session Logic

**Backend: GET /api/training/today**
- Returns today's training session with adaptive adjustments
- Combines:
  - Planned session from LLM-generated training plan
  - Current fatigue level from /api/cardio-coach
  - Historical feedback data

**Adaptation Rules:**

| Fatigue Level | Fatigue Ratio | Action |
|---------------|---------------|--------|
| 🟢 Green | ≤ 1.2 | Keep session as planned |
| 🟡 Orange | 1.2 - 1.5 | Reduce intensity/duration by 20%, convert intervals to easy |
| 🔴 Red | > 1.5 | Convert to recovery/Z1, reduce duration by 40-50% |

**Frontend: Adaptive Display**
- Shows fatigue status with color-coded badge
- Displays adaptation reason when applicable
- Original session shown grayed out
- Adaptive session highlighted with fatigue color border
- SessionCard component for consistent session display

### 3. Integration with Existing Systems

**Cardio Coach Integration**
- Reuses existing /api/cardio-coach endpoint
- Fatigue calculation based on:
  - HRV (Heart Rate Variability)
  - RHR (Resting Heart Rate)
  - Sleep hours and efficiency
  - Training load (ACWR)
- Falls back to mock data when Terra API unavailable

**Training Plan Integration**
- Works with existing LLM-generated plans
- Caches plan data (TTL: 1 hour)
- Maintains consistency with full cycle view

## Database Schema

### training_feedback Collection

```javascript
{
  user_id: String,
  date: String (ISO date),
  workout_id: String,
  status: String ('done' | 'missed'),
  created_at: DateTime
}
```

Indexes:
- `{user_id: 1, date: 1, workout_id: 1}` (unique)

## API Endpoints

### POST /api/training/feedback
Submit feedback for a training session.

**Request:**
```
POST /api/training/feedback?date=2026-04-04&workout_id=monday&status=done
Headers: X-User-Id: user123
```

**Response:**
```json
{
  "status": "success",
  "feedback": {
    "user_id": "user123",
    "date": "2026-04-04",
    "workout_id": "monday",
    "status": "done",
    "created_at": "2026-04-04T07:00:00Z"
  }
}
```

### GET /api/training/today
Get today's adaptive training session.

**Request:**
```
GET /api/training/today
Headers: X-User-Id: user123
```

**Response:**
```json
{
  "status": "success",
  "date": "2026-04-04",
  "day": "Friday",
  "planned_session": {
    "day": "Friday",
    "type": "Intervals",
    "duration": "60min",
    "distance_km": 10,
    "details": "6 x 1000m @ 4:00/km, 2min rest",
    "intensity": "hard",
    "estimated_tss": 85
  },
  "adaptive_session": {
    "day": "Friday",
    "type": "Endurance",
    "duration": "48min",
    "distance_km": 8,
    "details": "8.0 km • Easy pace • HR 130-145 bpm • Zone 2",
    "intensity": "easy",
    "estimated_tss": 60
  },
  "adaptation_applied": true,
  "adaptation_reason": "Moderate fatigue detected - intensity and duration reduced",
  "fatigue": {
    "fatigue_ratio": 1.35,
    "fatigue_status": "yellow",
    "recommendation": "EASY RUN",
    "recommendation_color": "yellow"
  },
  "recent_feedback": [...]
}
```

## Frontend Components

### TrainingPlan.jsx Updates

**New State:**
- `todaySession`: Stores today's adaptive session data
- `loadingToday`: Loading state for today's session
- `feedbackSubmitting`: Prevents duplicate submissions
- `sessionFeedback`: Tracks feedback status per workout

**New Functions:**
- `fetchTodaySession()`: Fetches adaptive session from API
- `handleFeedback(workoutId, status)`: Submits feedback and refreshes

**New Components:**
- `SessionCard`: Reusable component for displaying sessions
  - Props: session, isGrayed, fatigueColor
  - Handles styling based on session type and fatigue

### Translations

**English:**
- todayLabel: "Today's Session"
- feedbackDone: "Done"
- feedbackMissed: "Missed"
- adaptiveSession: "Adaptive Session"
- originalSession: "Original Session"
- feedbackSaved: "Feedback saved"

**French:**
- todayLabel: "Séance du jour"
- feedbackDone: "Réalisé"
- feedbackMissed: "Manqué"
- adaptiveSession: "Séance adaptative"
- originalSession: "Séance originale"
- feedbackSaved: "Feedback enregistré"

## Testing

### Manual Testing Steps

1. **Test Feedback Submission:**
   - Navigate to Training Plan
   - Click "Done" or "Missed" on today's session
   - Verify button changes color and is disabled
   - Check toast notification appears
   - Verify feedback saved in database

2. **Test Adaptive Sessions:**
   - Set different fatigue levels (mock or real data)
   - Verify session adapts correctly:
     - Green: No changes
     - Orange: 20% reduction, intervals → easy
     - Red: 50% reduction, converted to recovery
   - Check original session shows grayed out
   - Verify adaptive session has correct border color

3. **Test Fallback:**
   - Disconnect Terra API
   - Verify mock data is used
   - Confirm app still functions

### Automated Testing

Run the test script:
```bash
cd backend
python3 test_interactive_plan.py
```

## Edge Cases Handled

1. **No Terra API Connection:**
   - Falls back to mock cardio coach data
   - User can still see mock fatigue levels
   - Feedback still works

2. **No Session Planned:**
   - Returns status "no_session"
   - Frontend handles gracefully

3. **Duplicate Feedback:**
   - Upsert prevents duplicates
   - Latest feedback overwrites previous

4. **Missing Training Plan:**
   - Today endpoint returns graceful error
   - User prompted to generate plan

## Performance Considerations

### Caching
- Training plan cached with TTL 1h
- Cache key includes: user_id, week, phase, goal, vma, fatigue
- Feedback updates trigger session refresh (not full plan refresh)

### Database Queries
- Feedback query uses indexed fields
- Limited to 10 most recent feedback items
- Efficient date range queries for fatigue history

## Future Enhancements

Potential improvements:
1. Add "Partially Done" feedback option
2. Weekly feedback summary dashboard
3. ML-based adaptation (learn from user patterns)
4. Push notifications for today's session
5. Integration with calendar apps
6. Session rescheduling feature
7. Adaptation based on weather conditions
8. Social sharing of achievements

## Dependencies

**Backend:**
- Python 3.8+
- FastAPI
- Motor (async MongoDB)
- Existing CardioCoach modules

**Frontend:**
- React 18+
- Axios for API calls
- Lucide React for icons
- Sonner for toast notifications
- Existing UI components

## Deployment Notes

1. Ensure MongoDB has `training_feedback` collection
2. Create index: `db.training_feedback.createIndex({user_id: 1, date: 1, workout_id: 1}, {unique: true})`
3. No environment variables needed (uses existing config)
4. Frontend build includes new components
5. Backward compatible with existing plans

## Monitoring

Key metrics to track:
- Feedback submission rate
- Adaptation frequency by fatigue level
- User engagement with adaptive sessions
- API response times for /training/today
- Cache hit rate for training plans

## Troubleshooting

**Issue: Adaptive session not showing**
- Check /api/training/today response
- Verify training plan exists
- Check cardio-coach data availability

**Issue: Feedback not saving**
- Check MongoDB connection
- Verify user authentication
- Check browser console for errors

**Issue: Incorrect adaptation**
- Verify fatigue calculation in cardio-coach
- Check adaptation logic thresholds
- Review session type mapping

## Support

For issues or questions:
- Check logs: backend/logs/server.log
- Review API responses in browser DevTools
- Test with mock data first
- Verify database indexes exist
