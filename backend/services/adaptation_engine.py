def adapt_workout_advanced(planned_workout, fatigue_ratio, user_goal):

    workout = planned_workout.copy()

    # -------------------------
    # Fatigue tiers
    # -------------------------
    if fatigue_ratio > 1.6:
        return {
            "type": "rest",
            "label": "Rest Day – Active Recovery",
            "icon": "rest",
            "adaptation": "rest"
        }

    elif fatigue_ratio > 1.4:
        fatigue_level = "high"
        factor = 0.5

    elif fatigue_ratio > 1.2:
        fatigue_level = "moderate"
        factor = 0.7

    elif fatigue_ratio < 1.0:
        fatigue_level = "low"
        factor = 1.1

    else:
        fatigue_level = "normal"
        factor = 1.0

    # -------------------------
    # Adaptation par objectif
    # -------------------------

    if user_goal in ["5k", "10k"]:

        if workout["type"] == "intervals":
            workout["reps"] = max(1, int(workout.get("reps", 1) * factor))

        elif workout["type"] == "endurance":
            workout["duration"] = int(workout.get("duration", 30) * factor)

    elif user_goal in ["half_marathon", "marathon"]:

        if workout["type"] == "endurance":
            workout["duration"] = int(workout.get("duration", 30) * factor)

        elif workout["type"] == "intervals":
            workout["reps"] = max(2, int(workout.get("reps", 2) * factor))

    elif user_goal == "weight_loss":

        if fatigue_level == "high":
            return {
                "type": "recovery",
                "label": "Low Intensity Fat Burn – 30 min",
                "duration": 30,
                "icon": "run",
                "adaptation": "fatigue_override"
            }

        workout["duration"] = int(workout.get("duration", 30) * factor)

    else:
        if workout["type"] == "endurance":
            workout["duration"] = int(workout.get("duration", 30) * factor)

    workout["intensity"] = fatigue_level
    workout["adaptation"] = f"{fatigue_level}_{user_goal}"

    return workout