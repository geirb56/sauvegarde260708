"""
CardioCoach - Chat Engine 100% Python + RAG
Without any LLM (neither local, nor cloud, nor WebLLM)
Deterministic, fast (<1s), offline, natural, ultra-human
"""

import random
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

# Load the knowledge base
KNOWLEDGE_BASE_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

def load_knowledge_base() -> Dict:
    """Load the static knowledge base"""
    try:
        with open(KNOWLEDGE_BASE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading knowledge_base: {e}")
        return {}

KNOWLEDGE_BASE = load_knowledge_base()

# ============================================================
# TEMPLATES BY CATEGORY (10-15 variants per block)
# ============================================================

TEMPLATES = {
    # ==================== CATEGORY 1: FATIGUE ====================
    "fatigue": {
        "keywords": ["fatigue", "fatigué", "épuisé", "crevé", "lourd", "lourdeur", "épuisement", "vidé", "mort", "claqué", "cramé", "hs", "naze", "lessivé", "ko"],
        "intros": [
            "You really gave it all, respect! 💪",
            "Great mental strength to finish despite the heaviness!",
            "Bravo, you held on until the end 🔥",
            "You pushed hard, hats off!",
            "Even tired you gave it your all, that's huge!",
            "You managed like a boss despite everything 😅",
            "Respect for the effort despite the heaviness!",
            "You have a mental of steel!",
            "You nailed it big time!",
            "You're a warrior, even when it's tough!",
            "Great fight, you didn't give up!",
            "Hats off, you finished despite everything!",
            "Fatigue didn't get you, well done!",
            "You showed character today!",
            "Proud of you for holding on!"
        ],
        "analyses": [
            "Your pace dropped by {decrochage}% at the end with HR going up → you're clearly in accumulated fatigue. Your ratio is at {ratio}, which means you've loaded a lot without recovering enough.",
            "Heaviness at the end of the session → your recent load is high ({charge}), your body is telling you to slow down a bit. It's okay, it's normal.",
            "Ratio {ratio} elevated → slight overload, nothing alarming but need to calm things down a few days.",
            "You have a slight overload (ratio {ratio}) → it's not the end of the world but listen to your body.",
            "Your legs gave out at the end, it's a sign of fatigue accumulating. Normal after {nb_seances} sessions this week!",
            "HR climbing while pace drops = classic sign of fatigue. Your body is working hard to compensate.",
            "With {km_semaine} km this week, it's logical to feel some heaviness. Your body is absorbing the load.",
            "The fatigue you're feeling is your body adapting. It's a good sign if you recover well after!",
            "Your pace drop at the end shows you pushed well. It's positive, you're working your limits.",
            "When legs are heavy from the start, it's often a lack of recovery or hydration."
        ],
        "conseils": [
            "Tomorrow very easy run 40 min Z2 max or full day off, hydrate well and sleep early!",
            "Rest, take care of your legs with some gentle stretching. It'll recharge quickly.",
            "Lower the intensity for 2-3 days, your body will thank you and you'll come back stronger.",
            "Prioritize sleep and active recovery this week. That's where real progress happens!",
            "Take a full day off if you feel the need. Better one day of rest than an injury.",
            "Hydrate well (2L minimum), eat carbs and early to bed tonight!",
            "A little massage or foam roller on the legs can really help recovery.",
            "If fatigue persists more than 3 days, take a real deload week.",
            "Right now you need active recovery: walking, easy cycling, swimming... but no intense running.",
            "Listen to your body: if it says stop, it needs to recover to restart better."
        ],
        "relances": [
            "Was it heavy from km 3 or only at the end?",
            "How many hours have you slept these past few days?",
            "Hydration on point this week or did you skip a bit?",
            "Did you feel your legs heavy after how many km?",
            "Did you have soreness before this session?",
            "Is this the first time this week you feel like this?",
            "Are you eating enough carbs right now?",
            "Do you have work or personal stress that could be playing a role?",
            "Do you do stretching or foam roller after your sessions?",
            "Do you feel it's muscular fatigue or rather general?",
            "Do you feel a difference between your two legs?",
            "How many days have you been training without a break?"
        ]
    },

    # ==================== CATEGORY 2: PACE/CADENCE ====================
    "allure_cadence": {
        "keywords": ["allure", "cadence", "pace", "vitesse", "rythme", "tempo", "foulée", "pas", "spm", "min/km", "lent", "rapide", "vite"],
        "intros": [
            "So, let's talk technique! 🎯",
            "Good question about rhythm!",
            "Your pace, that's an important topic 👟",
            "Cadence is the key to an efficient stride!",
            "Ah pace, the nerve of performance!",
            "Great technical question!",
            "You're right to be interested in this!",
            "Cadence is often underestimated!",
            "Your current rhythm, let's break it down!",
            "Pace and cadence, the two pillars of performance!",
            "Good thinking about your stride!",
            "Smart to work on this!"
        ],
        "analyses": [
            "Your average cadence is {cadence} spm. {cadence_comment} The ideal is between 170 and 180, it reduces impact on joints.",
            "Your average pace of {allure}/km is {allure_comment}. Compared to your target zone, you're {zone_comment}.",
            "With a cadence of {cadence}, {cadence_detail}. A faster stride = less stress on knees.",
            "Your pace of {allure}/km shows that {allure_analysis}. It's consistent with your current level.",
            "Your pace variability is {variabilite}. {variabilite_comment}",
            "Looking at your recent runs, your cadence varies between {cadence_min} and {cadence_max}. {cadence_conseil}",
            "Your endurance pace ({allure}) corresponds well to zone {zone}. It's {zone_feedback}.",
            "With {km_semaine} km at {allure}/km average, you're working your base endurance well.",
            "Your current stride ({cadence} spm) is {foulée_comment}. We can optimize this!",
            "The gap between your easy pace and your tempo pace is {ecart}. That's {ecart_comment}."
        ],
        "conseils": [
            "To increase your cadence, do drills: high knees, butt kicks, 2x per week for 10 min.",
            "Try running to a metronome at 175 bpm for a few runs, you'll feel the difference!",
            "For pace, work on threshold sessions: 3x10 min at half-marathon pace with 3 min recovery.",
            "Short hills (30-60 sec) are great for naturally improving cadence.",
            "For a better stride: think about lifting knees and landing under your center of gravity.",
            "Integrate progressive accelerations (fartlek) into your easy runs to vary paces.",
            "Cadence work is better done on slight downhill at first, it's more natural.",
            "For specific pace, do one session per week of short intervals (200-400m).",
            "Think about relaxing shoulders and arms, it helps fluidify the stride.",
            "A good exercise: 4x30 sec fast / 30 sec slow to work on pace changes."
        ],
        "relances": [
            "Do you already do stride work or drills?",
            "Do you have a watch that gives you cadence in real-time?",
            "What pace are you aiming for in your next race?",
            "Have you tried the metronome for cadence?",
            "Do you feel a stride difference at the end of sessions?",
            "Do you feel you have a rather long or short stride?",
            "Do you do intervals regularly?",
            "Do you have pain that could be related to your stride?",
            "Do you run on forefoot, midfoot or heel?",
            "Are your shoes adapted to your stride?"
        ]
    },

    # ==================== CATEGORY 3: RECOVERY ====================
    "recuperation": {
        "keywords": ["récup", "recuperation", "repos", "récupérer", "off", "pause", "break", "relâche", "décharge", "régénération"],
        "intros": [
            "Recovery, that's where magic happens! ✨",
            "Ah recovery, the champions' secret!",
            "Good question, recovery is crucial!",
            "You're right to think recovery!",
            "Rest is also training!",
            "Smart to be interested in this! 🧠",
            "Recovery is 50% of progress!",
            "Recovering isn't being lazy, it's being smart!",
            "Good catch, many neglect this aspect!",
            "Active recovery, let's talk about it!",
            "Don't worry, I'll help you with this!",
            "This is THE important topic!"
        ],
        "analyses": [
            "With {nb_seances} sessions and {km_semaine} km this week, your body needs {recup_besoin}.",
            "Your load/recovery ratio is {ratio}. {ratio_comment} The green zone is between 0.8 and 1.2.",
            "Your last deload week was {derniere_decharge} ago. {decharge_comment}",
            "Looking at your load over the last 4 weeks, {charge_evolution}. {charge_conseil}",
            "You've chained {jours_consecutifs} days without rest. {consecutifs_comment}",
            "Your current volume ({km_semaine} km) compared to your average ({km_moyenne} km) is {volume_comment}.",
            "The quality of your recovery depends on your sleep, hydration and nutrition. {recup_analyse}",
            "After an intense session like this, count 48-72h for complete muscle recovery.",
            "Your body shows signs of {signes_recup}. It's {interpretation}.",
            "Active recovery (walking, light cycling) is more effective than total rest in your case."
        ],
        "conseils": [
            "Plan at least 1-2 days of rest or active recovery per week, it's non-negotiable.",
            "A deload week (volume -30-40%) every 3-4 weeks, that's the basis.",
            "Post-session: gentle stretching 10 min + 500ml water + protein snack within the hour.",
            "The foam roller 10-15 min on legs works miracles for recovery.",
            "Sleep before midnight = recovery x2. Sleep before midnight is more restorative.",
            "In active recovery, aim for 60-65% of your max HR, no more. That's real active rest.",
            "Cold baths (10-15°C, 10-15 min) after a big session reduce inflammation.",
            "Hydrate throughout the day, not just during and after effort.",
            "Regular massages (1x/month minimum) are an investment in your longevity.",
            "Listen to signals: heavy legs 2+ days = need more recovery."
        ],
        "relances": [
            "How many days off do you take per week usually?",
            "Do you have a post-session recovery routine?",
            "How many hours do you sleep on average?",
            "Do you use foam roller or get massages?",
            "Do you hydrate well throughout the day?",
            "How long ago was your last easy week?",
            "Do you feel you need more rest right now?",
            "Do you have soreness that persists more than 48h?",
            "Do you do active recovery like cycling or swimming?",
            "Have you tried cold baths or cold showers?"
        ]
    },

    # ==================== CATEGORY 4: PLAN/NEXT RUN ====================
    "plan": {
        "keywords": ["plan", "programme", "prochaine", "demain", "semaine", "planning", "organiser", "prévoir", "quoi faire", "entraînement"],
        "intros": [
            "Let's plan your week! 📅",
            "Ok, let's see what we can do!",
            "Good idea to plan ahead!",
            "I'll suggest a tailored plan!",
            "Let's go, let's organize all this!",
            "Here we go for your next session!",
            "I'm looking at your data and I'll tell you! 🔍",
            "You did well to ask!",
            "Let's optimize your week!",
            "Here's what I recommend!",
            "With what you've done, here's what's next!",
            "I'll make you a custom plan!"
        ],
        "analyses": [
            "This week you did {km_semaine} km over {nb_seances} sessions. {analyse_semaine}",
            "Your load/recovery ratio is {ratio}, so {ratio_implication} for what's next.",
            "Looking at your zones this week: {zones_resume}. {zones_conseil}",
            "Given your current load ({charge}), {charge_recommandation}.",
            "Your body has absorbed {km_semaine} km well, {adaptation_comment}.",
            "The intensity/endurance distribution this week is {repartition}. {repartition_comment}",
            "Your progress over the last month shows {progression}. We can {progression_action}."
        ],
        "conseils": [
            "Tomorrow I recommend: easy run 45-50 min in Z2, easy, to recover well.",
            "Your next quality session: 6x1000m at 10k pace with 2 min recovery. That'll do you good!",
            "This week, aim for: 1 long run (1h15-1h30), 1 tempo session, 2 easy runs.",
            "For your next run: free fartlek, 8-10 accelerations of 30 sec when you feel like it.",
            "I suggest a full rest day tomorrow, then easy restart on Tuesday.",
            "Next ideal session: hills! 8-10 reps of 45 sec, recovery jog down.",
            "Weekly plan: Monday off, Tuesday 40min run, Wednesday intervals, Thursday off, Friday run, Saturday long run.",
            "For variety: try a nature fartlek session, accelerate when you want, recover when you want.",
            "Your next long run: 1h20-1h30 at comfort pace, without looking at the watch, just by feeling.",
            "I suggest threshold work: 3x12 min at half-marathon pace, 3 min recovery between each."
        ],
        "relances": [
            "Do you have any specific constraints this week?",
            "Do you prefer running in the morning or evening?",
            "Do you have a race goal coming up?",
            "How many sessions can you fit in this week?",
            "Do you want to work on what priority: endurance or speed?",
            "Do you have access to a track or hills?",
            "Do you run alone or in a group?",
            "Do you have a max duration for your sessions?",
            "Do you want me to make you a plan for the full week?",
            "Are you more the regular type or does it depend on the weeks?"
        ]
    },

    # ==================== CATEGORY 5: WEEK ANALYSIS ====================
    "analyse_semaine": {
        "keywords": ["semaine", "bilan", "résumé", "analyse", "comment", "ça va", "forme", "état", "review", "point", "zones", "cardiaques", "cardiaque", "intensité", "endurance", "tempo"],
        "intros": [
            "Let's review your week! 📊",
            "Alright, I'll analyze all this!",
            "Let's see what you did!",
            "Week summary, here we go!",
            "I'm looking at your stats!",
            "Ok, let's dissect your week!",
            "Your weekly review, here it is!",
            "Complete analysis incoming!",
            "I'll give you the rundown!",
            "Let's look at this together!",
            "Your week in summary!",
            "It's review time!"
        ],
        "analyses": [
            "This week: {km_semaine} km over {nb_seances} sessions, {duree_totale} of running. {appreciation}",
            "Zone-wise: {z1z2}% in endurance, {z3}% in tempo, {z4z5}% in intensive. {zones_verdict}",
            "Your load is {charge_niveau} with a ratio of {ratio}. {charge_interpretation}",
            "Compared to last week: {comparaison_km} in volume, {comparaison_intensite} in intensity.",
            "Your average pace ({allure}/km) is {allure_evolution} compared to usual.",
            "You ran {nb_jours} days out of 7. {regularite_comment}",
            "Your session distribution: {repartition_types}. {repartition_verdict}",
            "Your feelings this week seem {sensations}. {sensations_conseil}",
            "Strong point: {point_fort}. Point to improve: {point_ameliorer}.",
            "In summary: {resume_global}. {conseil_global}"
        ],
        "conseils": [
            "For next week, I recommend you {conseil_semaine_prochaine}.",
            "Keep it up! Maintain this volume and regularity.",
            "Think about adding an active recovery session to better absorb the load.",
            "Next week, try to add a bit more work in Z3-Z4.",
            "Well done! To progress further, vary the session types a bit more.",
            "Your endurance base is solid. You can start adding specific work.",
            "Careful not to increase too fast. The rule is 10% max per week!",
            "For what's next, I suggest a consolidation week before increasing.",
            "You're on the right track! Stay regular and progress will come.",
            "Think about integrating one long run per week if it's not already done."
        ],
        "relances": [
            "How did you feel overall this week?",
            "Do you have any pain or discomfort to report?",
            "Does the volume seem manageable or a bit too much?",
            "Were you able to complete all planned sessions?",
            "Do you want us to adjust the plan for next week?",
            "Are you satisfied with your week?",
            "Were there sessions you found too hard?",
            "Do you want to talk about a specific aspect?",
            "Did you recover well between sessions?",
            "Any specific goals for next week?"
        ]
    },

    # ==================== CATEGORY 6: MOTIVATION ====================
    "motivation": {
        "keywords": ["motivation", "motivé", "démotivé", "envie", "flemme", "dur", "difficile", "lassé", "ennui", "routine", "marre", "abandonner", "moral"],
        "intros": [
            "Hey, it's normal to have rough patches! 💙",
            "Motivation comes and goes, don't worry!",
            "I understand, we all go through this!",
            "It's human to feel like this!",
            "Hey, even the pros have off days!",
            "You're not alone, it happens to everyone!",
            "Lack of motivation is a signal, not a weakness!",
            "We'll find a solution together!",
            "It's ok not to be at 100% all the time!",
            "Running is a marathon, not a sprint... literally! 😄",
            "Your honesty is already a good sign!",
            "We'll get the machine going again!"
        ],
        "analyses": [
            "When motivation drops, it's often a sign of accumulated fatigue or too monotonous routine.",
            "Given your history, you've done {km_total} km these past weeks. {charge_impact_motivation}",
            "Weariness can come from goals that are too distant or not stimulating enough.",
            "Sometimes the body says stop before the mind. Lack of motivation can be a signal that recovery is needed.",
            "Routine kills motivation. If you keep doing the same routes, it's normal to get saturated.",
            "Overtraining has lack of motivation as a classic symptom. {surentrainement_check}",
            "Running alone all the time can weigh on morale in the long run.",
            "In winter, weather and light naturally impact motivation.",
            "If you don't have a clear goal, it's hard to stay motivated long-term.",
            "Comparison with others on social media can also demotivate. Focus on YOUR journey!"
        ],
        "conseils": [
            "Change your route! Discover a new area, it often reboots motivation.",
            "Set yourself a mini achievable goal this week: just 3 runs, no matter the duration.",
            "Try running with someone, even once. It changes everything!",
            "Allow yourself a real break of 4-5 days. Sometimes it's the best remedy.",
            "Sign up for a small fun race, it gives a concrete goal.",
            "Listen to a new podcast or music you love during your run.",
            "Forget the watch for one run. Run by feeling, for pleasure.",
            "Remember why you started. What was your initial motivation?",
            "Vary activities: cycling, swimming, hiking... Cross-training can restart the desire.",
            "Reward yourself after a good week. You deserve it!"
        ],
        "relances": [
            "Since when have you been feeling like this?",
            "Do you have a race goal right now?",
            "Do you always run alone or sometimes in a group?",
            "Do you have varied routes or is it always the same?",
            "Is there an aspect of your life that could impact your morale?",
            "Have you tried running without a watch recently?",
            "Is it more physical or mental laziness?",
            "Are you sleeping well right now?",
            "Have you taken a running break recently?",
            "What motivated you at the beginning?"
        ]
    },

    # ==================== CATEGORY 7: WEATHER ====================
    "meteo": {
        "keywords": ["météo", "temps", "pluie", "vent", "chaud", "froid", "chaleur", "canicule", "orage", "neige", "verglas", "humidité"],
        "intros": [
            "Ah weather, it changes everything! 🌤️",
            "Good catch thinking about conditions!",
            "Weather, you have to know how to adapt!",
            "Running in all weathers is an art!",
            "Conditions are important to manage!",
            "Good question, it really impacts performance!",
            "Adapting to weather means being a real runner!",
            "Weather, we can't change it, but we can prepare for it!",
            "You're right to wonder about this!",
            "External conditions, let's talk about them!"
        ],
        "analyses": [
            "In hot weather (+25°C), the body spends more energy cooling down. Result: same effort = slower pace.",
            "Headwind can cost you 10-20 sec/km at equivalent effort. It's not you being worse!",
            "In cold weather (<5°C), muscles take longer to warm up. Warm-up is crucial.",
            "High humidity (>70%) makes heat evacuation more difficult. Your body overheats faster.",
            "Light rain doesn't really impact performance if you're well equipped. It's even refreshing!",
            "In strong heat, your HR will be naturally higher for the same pace. It's physiological.",
            "Dry cold is easier to manage than humid cold. Humidity goes through layers.",
            "Difficult conditions strengthen the mental. It's an investment for races!",
            "Running in bad weather prepares you for all situations on race day.",
            "Weather also impacts your recovery. In strong heat, hydrate even more after."
        ],
        "conseils": [
            "In heat: slow down by 15-30 sec/km, hydrate every 15-20 min, wet your cap.",
            "In cold weather: layer up well (3 layers), protect your extremities, extend warm-up to 15 min.",
            "In strong wind: start facing the wind and return with wind at your back. You'll have more energy to finish!",
            "In rain: technical clothes that dry fast, cap, and plan spare socks.",
            "In strong heat: run early morning or late evening, avoid 12pm-4pm at all costs.",
            "In humid weather: choose breathable clothes and avoid cotton which retains moisture.",
            "In winter: a neck warmer or buff protects airways from cold well.",
            "In difficult conditions: reduce your time goals and focus on perceived effort.",
            "Think about checking the weather before choosing your route (shade/sun, sheltered/exposed).",
            "Always adapt your outfit to the felt temperature, not the displayed temperature!"
        ],
        "relances": [
            "Do you run morning or evening right now?",
            "Do you have more sheltered routes for windy days?",
            "Do you hydrate enough in hot weather?",
            "Do you have an outfit adapted to all conditions?",
            "Do you prefer postponing or adapting to conditions?",
            "Have you ever run in pouring rain?",
            "Does cold bother you or do you like it?",
            "Do you have a warm-up routine in cold weather?",
            "Do you run with a cap in strong heat?",
            "Does weather impact your motivation a lot?"
        ]
    },

    # ==================== CATEGORY 7b: HEART RATE ZONES ====================
    "zones": {
        "keywords": [],  # Detection via detect_intent
        "intros": [
            "Let's talk about your heart rate zones! 💓",
            "Zones are the key to training!",
            "Zone balance, super important!",
            "Your heart rate zones, let's analyze!",
            "Zone distribution, I love this topic!"
        ],
        "analyses": [
            "Your current distribution: Z1-Z2 (endurance) = {z1z2}%, Z3 (tempo) = {z3}%, Z4-Z5 (intensive) = {z4z5}%. {zones_verdict}",
            "The ideal to progress: 80% in Z1-Z2 (endurance), 15-20% in Z3-Z4. You're at {z1z2}% in endurance.",
            "Zone 2 (base endurance) is THE zone where you should spend most time. It develops your aerobic base.",
            "Too much Z3 (tempo zone) = risk of chronic fatigue without real gains. Aim for Z2 + Z4 with less Z3.",
            "With {z4z5}% in high zones (Z4-Z5), {zones_conseil}"
        ],
        "conseils": [
            "To balance: add 1-2 pure Z2 runs (conversation possible) per week. Counter-intuitive but it works!",
            "The 80/20 rule: 80% of time in easy endurance, 20% in intensity. Simple but effective.",
            "To know if you're in Z2: you should be able to talk easily. If you're breathing hard, you're too high.",
            "A permanent Z3 run = the 'gray zone'. Not easy enough to recover, not hard enough to progress. Avoid!",
            "My advice: make your easy runs REALLY easy, and your hard sessions REALLY hard. No soft middle ground.",
            "To increase your Z2: run with a heart rate monitor and stay under 75% of your max HR. Frustrating at first but pays off!"
        ],
        "relances": []
    },

    # ==================== CATEGORY 7c: FEELINGS ====================
    "sensations": {
        "keywords": [],  # Detection via detect_intent
        "intros": [
            "How you feel is important! 😊",
            "Feelings, the best indicator!",
            "Listening to your body is the basis!",
            "Your feelings matter enormously!",
            "How you feel, often more reliable than numbers!"
        ],
        "analyses": [
            "Feeling good is a sign your body is absorbing the load well. Your ratio of {ratio} confirms you're in good balance.",
            "Good feelings = good adaptation to training. Keep it up!",
            "Your body is talking to you: if you feel good, it's that your plan is working. {km_semaine} km this week is {volume_comment}.",
            "Daily form varies, it's normal! What matters is the trend over several weeks.",
            "Your feelings today often reflect what you did 2-3 days ago. Fatigue is delayed."
        ],
        "conseils": [
            "Take advantage of this good form for a quality session if you haven't done one recently!",
            "When you feel good, it's the ideal time for a long run or threshold session.",
            "Note your feelings after each run (1-10). It helps detect trends long-term.",
            "If you feel good several days in a row, you can slightly increase intensity or volume.",
            "Feelings matter more than numbers. If you feel tired despite good stats, listen to your body!",
            "Enjoy this good feeling! It's a sign your training is well dosed. 💪"
        ],
        "relances": []
    },

    # ==================== CATEGORY 8: NUTRITION ====================
    "nutrition": {
        "keywords": ["nutrition", "manger", "alimentation", "glucides", "protéines", "hydratation", "boire", "eau", "gel", "boisson", "repas", "petit-déjeuner", "récup", "crampe"],
        "intros": [
            "Nutrition is the fuel! ⛽",
            "Eating well = running well!",
            "Nutrition, crucial topic!",
            "Your body needs the right fuel!",
            "Nutrition, often neglected but essential!",
            "What you eat directly impacts your performance!",
            "Good question, let's talk food! 🍝",
            "Hydration and nutrition, the basics!",
            "You're right to be interested!",
            "Runner's diet is important!"
        ],
        "analyses": [
            "Running consumes about 1 kcal/kg/km. Over {km_semaine} km, you need to compensate!",
            "Carbs are the runner's main fuel. They should represent 50-60% of your diet.",
            "Hydration directly impacts performance. 2% dehydration = -10% performance.",
            "Proteins (1.2-1.6g/kg/day) are essential for muscle recovery.",
            "Timing is important: eat 2-3h before effort, refuel within 30min after.",
            "Cramps are often linked to lack of sodium or magnesium.",
            "A varied diet generally covers all needs without supplements.",
            "Coffee (caffeine) can improve performance by 2-3% if taken 1-2h before.",
            "Alcohol the night before impacts sleep quality and thus recovery.",
            "Fiber is important but avoid just before a session (digestive discomfort)."
        ],
        "conseils": [
            "Before a long run: carb-rich meal 2-3h before (pasta, rice, bread).",
            "During effort (+1h30): 30-60g carbs/hour (gels, energy drink, dried fruits).",
            "After effort: within 30 min, carbs + protein snack (banana + yogurt, chocolate milk).",
            "Hydrate throughout the day, not just during and after effort.",
            "In hot weather, add salt to your drink or eat salty foods.",
            "Avoid fatty foods and fiber in the 3h before an intense session.",
            "Pre-race breakfast: bread, jam, banana, coffee. Tested and approved!",
            "Dried fruits (apricots, dates) are perfect during long runs.",
            "Never test new food or gel on race day. Always in training!",
            "For recovery, plant proteins (legumes) are as effective as animal ones."
        ],
        "relances": [
            "What do you usually eat before your runs?",
            "Do you hydrate during your sessions?",
            "Have you had digestive problems while running?",
            "Do you take gels or bars on long runs?",
            "Do you eat within 30 min after your session?",
            "Do you get cramps regularly?",
            "How many liters do you drink per day approximately?",
            "Do you have a typical breakfast before a race?",
            "Do you avoid certain foods before running?",
            "Do you take dietary supplements?"
        ]
    },

    # ==================== CATEGORY 9: INJURIES ====================
    "blessures": {
        "keywords": ["blessure", "douleur", "mal", "genou", "cheville", "tibia", "tendon", "hanche", "mollet", "pied", "dos", "périostite", "bandelette", "aponévrose", "contracture"],
        "intros": [
            "Ouch, let's talk about this pain 🩹",
            "Pain shouldn't be neglected!",
            "Ok, let's see what's happening!",
            "Your body is sending you a signal, let's listen!",
            "Injuries are serious, let's talk about it!",
            "Careful with this discomfort!",
            "I'll help you see more clearly!",
            "Prevention is the key!",
            "Your body is talking, let's listen!",
            "A pain = a message, let's decode it!"
        ],
        "analyses": [
            "A pain that persists more than 3 days deserves medical or physio advice.",
            "Knee pain often comes from hip/glute imbalance or unsuitable stride.",
            "Shin splints are often caused by too rapid volume increase.",
            "IT band manifests as external knee pain, often downhill.",
            "Achilles tendonitis requires rest and eccentric exercises.",
            "Plantar pain (fasciitis) is common in runners with high load.",
            "Muscle pain (soreness) ≠ joint or tendon pain.",
            "Volume increase of more than 10%/week is cause #1 of injuries.",
            "Lack of strength training predisposes to injuries.",
            "Worn shoes (>800km) significantly increase injury risk."
        ],
        "conseils": [
            "Golden rule: if it hurts while running and gets worse, STOP. Rest is better than a long injury.",
            "RICE in 48h: Rest, Ice, Compression, Elevation.",
            "If joint pain, consult a physio specialized in running, not just your GP.",
            "Hip and glute strengthening prevents 80% of runner injuries.",
            "Knee: work squats, lunges, and glute bridge. It stabilizes the whole chain.",
            "Shin splints: rest 1-2 weeks, then very progressive restart. No possible shortcut.",
            "Achilles tendon: eccentric exercises (lower on tiptoe, slowly). 3x15/day.",
            "IT band: foam roller on outside of thigh + IT band stretches.",
            "Calf: check your shoes, often linked to too low drop or too fast transition.",
            "Prevention: 15 min of strength 3x/week is enough to drastically reduce risk."
        ],
        "relances": [
            "How long have you had this pain?",
            "Is it while running, after, or all the time?",
            "Have you changed something recently (shoes, volume, terrain)?",
            "Is the pain precisely localized or diffuse?",
            "Does it improve with warm-up or get worse?",
            "Have you had this pain before?",
            "Have you seen a physio or sports doctor?",
            "Do you do strength training regularly?",
            "How many km do your shoes have?",
            "Does the pain wake you at night?"
        ]
    },

    # ==================== CATEGORY 10: PROGRESSION / STAGNATION ====================
    "progression": {
        "keywords": ["progresser", "progressé", "stagne", "stagnation", "plateau", "bloqué", "évoluer", "avancer", "améliorer", "mieux", "indicateur", "surveiller"],
        "intros": [
            "Good question about progression! 📈",
            "Monitoring your progression is key!",
            "Let's look at the important indicators!",
            "You're right to want to measure your progress!",
            "To progress, you first need to know where you are!",
            "The right indicators change everything!"
        ],
        "analyses": [
            "Key indicators to monitor:\n• **Average pace** (your current {allure}/km)\n• **Resting HR** (if it drops = progress)\n• **Cadence** (currently {cadence} spm)\n• **Feelings** during effort\n• **Recovery time** after sessions",
            "To measure your progress, compare over 4-8 weeks:\n1. Your pace per km on easy runs\n2. Your average HR at same pace\n3. Your times on reference routes",
            "With your volume of {km_semaine} km/week and pace of {allure}/km, the indicators to monitor are: pace, cadence, and especially feelings at same effort.",
            "HR is a great indicator: if you run at {allure}/km with lower HR than before, you're progressing! Even if pace hasn't changed.",
            "To track your progress:\n• **Short term**: feelings, recovery\n• **Medium term** (4 weeks): pace, HR at equal effort\n• **Long term** (3+ months): 5/10km times, VO2max",
        ],
        "conseils": [
            "The 5 essential indicators:\n1️⃣ Pace per km (on flat route)\n2️⃣ Resting HR upon waking\n3️⃣ HR at given pace\n4️⃣ Cadence (spm)\n5️⃣ Subjective feelings (1-10)",
            "Create a reference route (3-5km flat) that you do once a month at full effort. Compare times!",
            "Note your feelings after each run (1-10). If you run faster with same feelings = progress!",
            "Resting HR is an underestimated indicator. Measure it every morning on waking. If it drops over several weeks, you're improving.",
            "Compare your Z2 (endurance) paces: if you run faster at same HR, you're progressing in running economy.",
            "The #1 indicator for me: can you hold your pace longer than before? If yes, you're progressing!"
        ],
        "relances": []
    },

    # ==================== CATEGORY 11: RACE PREP ====================
    "prepa_course": {
        "keywords": ["course", "compétition", "10km", "semi", "marathon", "trail", "prépa", "objectif", "dossard", "inscription", "jour j"],
        "intros": [
            "A race coming up, great! 🏃‍♂️",
            "Race prep is exciting!",
            "Your goal is approaching!",
            "We'll prepare you to the top!",
            "Let's go for the prep!",
            "Your bib is waiting!",
            "Racing is THE motivation!",
            "We'll plan everything!",
            "Alright, goal in sight!",
            "Your race deserves a real prep!"
        ],
        "analyses": [
            "For a 10km, count 8-10 weeks of prep. For a half-marathon, 10-12. For a marathon, 12-16.",
            "At {jours_course} days from your race, you're in the {phase_prepa} phase. {phase_conseil}",
            "Given your current pace ({allure}/km), your potential on {distance} is around {temps_estime}.",
            "Your current load ({km_semaine} km/week) is {charge_comment} to prepare a {distance}.",
            "The last long run should be 2-3 weeks before the race, not less.",
            "The week before the race: -50% volume, maintain some light intensity.",
            "Your specific work at target pace should represent 10-15% of total volume.",
            "Your heart rate zones show {zones_analyse}. {zones_recommandation}",
            "On race day, start at a pace 5-10 sec slower than your goal for the first 5km.",
            "Race management (pacing) is as important as physical form."
        ],
        "conseils": [
            "Last week: reduce volume by 50%, keep 2-3 short accelerations to stay sharp.",
            "Test EVERYTHING in training: shoes, outfit, nutrition, gel. Nothing new on race day!",
            "Scout the course if possible, or study it on Google Maps. Knowing where hills are helps.",
            "Prepare your stuff the night before, with a checklist. Less stress on race day.",
            "Sleep well 2 nights before (the night before, stress can disrupt sleep, it's normal).",
            "Arrive early on race day: parking, bib pickup, warm-up, bathroom... it takes time.",
            "Pre-race warm-up: 10-15 min of jogging + a few progressive accelerations.",
            "Race strategy: start cautiously, accelerate progressively, finish strong if possible.",
            "Visualize your race the night before: the start, the course, your sensations, the finish.",
            "Post-race: walk, stretch, eat and drink within the hour. Recovery starts right away!"
        ],
        "relances": [
            "What's your next race?",
            "How far away is it?",
            "Do you have a time goal?",
            "Is this your first race at this distance?",
            "Have you already made a prep plan?",
            "Do you know the course?",
            "Have you planned your nutrition strategy during the race?",
            "Do you have an outfit planned?",
            "Are you running alone or with a group/pacer?",
            "Are you more stressed or calm before races?"
        ]
    },

    # ==================== CATEGORY 12: MENTAL/STRESS ====================
    "mental": {
        "keywords": ["mental", "stress", "anxiété", "pression", "peur", "confiance", "doute", "nerveux", "angoisse", "trac"],
        "intros": [
            "Mental is 50% of running! 🧠",
            "Stress can be managed!",
            "You're not alone feeling this!",
            "Mental is trained like physical!",
            "Normal to have nerves!",
            "Pressure, we'll tame it!",
            "Your mental is your hidden strength!",
            "Doubt happens to everyone!",
            "We'll work on this aspect together!",
            "Confidence is built!"
        ],
        "analyses": [
            "Pre-race stress is normal and even useful: it prepares your body for performance.",
            "Doubt is normal, even champions have it. The difference: they run anyway.",
            "Chronic stress impacts recovery and progress. It must be taken into account.",
            "Positive visualization activates the same brain areas as real action. It's powerful!",
            "The 'wall' in racing is often more mental than physical. Your body can do much more than you think.",
            "Negative thoughts come, it's normal. What matters is not feeding them.",
            "Confidence comes from preparation. If you're well prepared, you can be confident.",
            "Performance stress can improve your results (good stress) or tank them (bad stress).",
            "Pre-race routines reduce anxiety: always the same warm-up, the same outfit...",
            "Disturbed sleep before a race is very common. It's the night before-before that counts."
        ],
        "conseils": [
            "Box breathing before start: inhale 4s, hold 4s, exhale 4s, hold 4s. Repeat 5x.",
            "Visualize your race in detail the night before: start, course, sensations, triumphant finish.",
            "Break the race into segments: 'just to the next aid station', 'just 2 more km'...",
            "Prepare 2-3 personal mantras for tough moments: 'I'm strong', 'One step at a time'...",
            "Focus on what you control (your prep, your race) not what you don't control (others, weather).",
            "If doubt comes, remember your training. You did the work.",
            "On race day, avoid negative or stressed people. Surround yourself with good vibes.",
            "Accept that the race may not be perfect. No race ever is.",
            "Celebrate being at the starting line. Many people don't even dare sign up.",
            "If you panic, return to your breathing. It's the basis of mental control."
        ],
        "relances": [
            "What stresses you most?",
            "Have you tried visualization?",
            "Do you sleep well before races?",
            "Do you have mantras or phrases that help you?",
            "Is stress more before or during the race?",
            "Do you have pre-race routines?",
            "Is it the time that puts pressure on you or something else?",
            "Have you had a mental 'wall' in a race?",
            "Do you meditate or do relaxation?",
            "Can you put things in perspective or is it difficult?"
        ]
    },

    # ==================== CATEGORY 13: SLEEP ====================
    "sommeil": {
        "keywords": ["sommeil", "dormir", "dodo", "nuit", "insomnie", "fatigue", "sieste", "repos", "réveil", "coucher"],
        "intros": [
            "Sleep is the best legal doping! 😴",
            "Sleeping well = running well!",
            "Night recovery, crucial topic!",
            "Sleep, often neglected but essential!",
            "You're right to be interested!",
            "Rest is also training!",
            "Your sleep directly impacts your performance!",
            "At night is when your body repairs!",
            "Let's talk sleep!",
            "Sleep, the champions' secret weapon!"
        ],
        "analyses": [
            "Deep sleep is the phase where your muscles repair and growth hormone is secreted.",
            "Chronic sleep deprivation increases injury risk by 60%.",
            "7-9h of sleep are recommended for a regular runner. During high load periods: rather 8-9h.",
            "Sleep before midnight is more restorative: first cycles are deeper.",
            "Quality matters as much as quantity. 7h of good sleep > 9h of interrupted sleep.",
            "Stress and blue screens disrupt melatonin production (sleep hormone).",
            "After an intense session, the body needs more sleep to recover.",
            "Coffee after 2pm can impact your sleep even if you don't feel it.",
            "Ideal bedroom temperature for sleep: 18-19°C.",
            "Sleep debt accumulates and impacts performance over several days."
        ],
        "conseils": [
            "Evening routine: screens off 1h before, lukewarm shower, reading, bed at fixed time.",
            "If you sleep poorly, a 20 min nap (no more) can compensate without disrupting the night.",
            "Avoid heavy meals in the evening, digestion disturbs sleep.",
            "Magnesium can help if you have trouble falling asleep or nighttime cramps.",
            "Cool, dark and quiet room = optimal conditions.",
            "If stress prevents sleep: gratitude journal or to-do list to 'empty' the mind.",
            "Before a race, it's the night before-before that counts. Don't stress if you sleep poorly D-1.",
            "Waking at fixed time (even weekends) regulates sleep better than fixed bedtime.",
            "Avoid alcohol in the evening: it makes you sleepy but disturbs deep sleep quality.",
            "During high load periods, prioritize sleep over everything else. That's where you progress."
        ],
        "relances": [
            "How many hours do you sleep on average?",
            "Do you fall asleep easily or does it take time?",
            "Do you wake up fresh or tired?",
            "Do you have a routine before sleeping?",
            "Do you look at screens late in the evening?",
            "Do you wake up often at night?",
            "Do you take naps?",
            "Do you sleep better or worse after big sessions?",
            "Does stress impact your sleep?",
            "Have you tried relaxation techniques?"
        ]
    },

    # ==================== CATEGORY 14: STRENGTH TRAINING ====================
    "renforcement": {
        "keywords": ["renfo", "renforcement", "musculation", "muscle", "gainage", "squat", "pompe", "abdos", "fessiers", "force", "gym"],
        "intros": [
            "Strength training, the anti-injury weapon! 💪",
            "Runner's strength training, important topic!",
            "Good catch thinking about strengthening!",
            "Strength training isn't just for bodybuilders!",
            "Strength in service of running!",
            "Core work, the foundation of everything!",
            "You're right, strength training is crucial!",
            "A strong runner is an efficient runner!",
            "Strengthening, let's talk about it!",
            "Prevention through strength training!"
        ],
        "analyses": [
            "Core work strengthens your trunk and stabilizes your stride. Less wasted energy = more efficiency.",
            "Glutes are the most powerful muscles in stride. Neglecting them = guaranteed injuries.",
            "80% of runner injuries could be avoided by regular strength training.",
            "No gym needed: bodyweight exercises are largely sufficient.",
            "Strength training improves running economy: you spend less energy for same speed.",
            "2-3 sessions of 15-20 min per week are enough to see results.",
            "Squats and lunges work the entire propulsion chain: quads, glutes, calves.",
            "Glute bridge isolates glutes well without stressing knees.",
            "Calves are often neglected but essential for cushioning and propulsion.",
            "Strength training won't bulk you up if you stay in high repetitions."
        ],
        "conseils": [
            "Basic routine: 3x30s core (front plank + sides), 3x12 squats, 3x10 lunges each leg.",
            "Glute bridge: lying on back, feet on ground, raise pelvis. 3x15 reps.",
            "For calves: calf raises (bilateral then unilateral). 3x15 reps.",
            "Superman strengthens lower back: lying face down, raise arms and legs. 3x10.",
            "Do strength training after an easy session, not before an intense one.",
            "Jump rope is great for calves and proprioception. 3x1 min.",
            "Step-up on step works balance and unilateral strength. 3x10 each leg.",
            "Clam shell strengthens hip abductors. 3x15 each side.",
            "Not motivated for strength training? Do it in front of a Netflix show, it goes better!",
            "Integrate strength into your routine: even 10 min 3x per week makes a difference."
        ],
        "relances": [
            "Do you currently do strength training?",
            "Do you have equipment or work with bodyweight?",
            "Do you prefer standing or floor exercises?",
            "Do you have areas to strengthen as priority?",
            "Do you do strength before or after your runs?",
            "Do you have pain that could be related to lack of strength?",
            "Do you know the basic exercises for runners?",
            "Can you be regular with strength training?",
            "Have you followed a specific strength program?",
            "Core work, do you do it?"
        ]
    },

    # ==================== CATEGORY 15: EQUIPMENT ====================
    "equipement": {
        "keywords": ["équipement", "chaussure", "basket", "montre", "gps", "tenue", "vêtement", "chaussette", "sac", "ceinture", "lampe", "frontale"],
        "intros": [
            "Equipment is important! 👟",
            "Let's talk gear!",
            "Well equipped = well prepared!",
            "Shoes, crucial topic!",
            "The right equipment makes the difference!",
            "You're right to be interested!",
            "Equipment, a smart investment!",
            "Your gear, let's talk about it!",
            "Getting well equipped is the basis!",
            "The right tools to run well!"
        ],
        "analyses": [
            "Worn shoes (>600-800 km) lose their cushioning and increase injury risk.",
            "Shoe type must match your stride (pronator, neutral, supinator) and your terrain.",
            "A GPS watch isn't essential but helps enormously to track progress.",
            "Technical clothes evacuate sweat, unlike cotton which retains it.",
            "The drop (heel/forefoot difference) impacts stride. Too rapid transition to low-drop = injury.",
            "Running socks reduce friction and blisters.",
            "A hydration belt is useful for runs over 1h, especially in hot weather.",
            "Headlamp is essential for running early morning or evening in winter.",
            "Sunglasses reduce visual fatigue and protect from UV.",
            "Testing in specialized store is the best way to find THE right shoe."
        ],
        "conseils": [
            "Change your shoes every 600-800 km, or as soon as you feel less cushioning.",
            "Go to a specialized running store for stride test and personalized advice.",
            "Have 2 pairs of shoes in rotation: it prolongs their lifespan and varies stimuli.",
            "Test your race shoes in training, never on race day!",
            "For trail, choose shoes with grip and protection.",
            "Seamless clothes reduce friction on long distances.",
            "A basic watch with GPS is more than enough to start. No need for the latest model.",
            "Invest in good socks: often neglected but it changes everything.",
            "In cold weather, favor thin layers you can stack rather than a big puffer.",
            "Hydration pack type vest is more comfortable than belt for trail."
        ],
        "relances": [
            "How many km do your shoes have?",
            "Do you know your stride type?",
            "Were you advised in specialized store?",
            "What terrain do you mainly run on?",
            "Do you have a GPS watch?",
            "Do you have blister problems?",
            "Are your shoes comfortable from the start or does it rub?",
            "Do you alternate several pairs?",
            "Do you have the right equipment for all weather conditions?",
            "Do you wear technical clothes or cotton?"
        ]
    },

    # ==================== CATEGORY 16: HEAT ====================
    "chaleur": {
        "keywords": ["chaleur", "chaud", "canicule", "été", "soleil", "surchauffe", "coup de chaud", "déshydratation", "transpiration"],
        "intros": [
            "Running in heat can be managed! ☀️",
            "Heat, you have to adapt!",
            "Good question about heat management!",
            "Summer is a challenge for runners!",
            "Heat requires adjustments!",
            "You're right, it's an important topic!",
            "Running in cool is better but not always possible!",
            "Heat, we can tame it!",
            "Managing heat is essential!",
            "Heat acclimatization, let's talk!"
        ],
        "analyses": [
            "In strong heat (+30°C), your body spends a lot of energy to cool down. Result: -15 to 30 sec/km at equivalent effort.",
            "Humidity worsens heat effect: sweat no longer evaporates, body overheats.",
            "Heat stroke warning signs: nausea, dizziness, confusion, sweating stops. Immediate STOP!",
            "Heat acclimatization takes 10-14 days. After, the body adapts better.",
            "2% dehydration reduces performance by 10-20%. And you lose 1-2L/h in strong heat.",
            "Your HR will be naturally 10-15 bpm higher in hot weather for same pace.",
            "The body can't cool effectively beyond 35°C with high humidity.",
            "Running in heat is additional stress. Your perceived load is higher.",
            "Hydration must start BEFORE effort, not during. Arrive already well hydrated.",
            "Light clothes reflect heat, dark ones absorb it."
        ],
        "conseils": [
            "In strong heat, slow down by 15-30 sec/km and forget the time. Effort counts, not pace.",
            "Run early morning (6am-8am) or late evening (after 8pm). Avoid 12pm-4pm at all costs.",
            "Hydrate BEFORE: 500ml in the 2h before effort.",
            "During effort: 150-250ml every 15-20 min, with salts if +1h.",
            "Wet your cap, neck, forearms at water points. External cooling helps.",
            "Choose shaded routes close to fountains or water points.",
            "Light, breathable, loose clothes. No cotton!",
            "If you feel bad (nausea, dizziness): STOP, get in shade, drink, and call for help if needed.",
            "After the run: keep drinking, eat water-rich foods (watermelon, cucumber...).",
            "To acclimatize: 10-14 days of moderate runs in heat, increasing progressively."
        ],
        "relances": [
            "Do you run morning or evening in summer?",
            "Do you have shaded routes?",
            "Do you drink enough before leaving?",
            "Do you carry water with you?",
            "Have you had heat strokes?",
            "Do you wear a cap?",
            "Are your clothes adapted to heat?",
            "Do you know how to recognize overheating signs?",
            "Do you adapt your pace when it's hot?",
            "Can you run regularly in summer?"
        ]
    },

    # ==================== CATEGORY 17: POST-RACE ====================
    "post_course": {
        "keywords": ["après", "post", "marathon", "récup", "courbature", "récupération", "course terminée", "finisher"],
        "intros": [
            "Congrats on your race, finisher! 🏅",
            "Post-race recovery is crucial!",
            "Well done finishing!",
            "After effort, comfort... and recovery!",
            "Your race is done, now recover!",
            "Congratulations, let's talk recovery!",
            "Post-race, time to take care of yourself!",
            "Your body needs to recover now!",
            "Recovery is part of performance!",
            "Recover well = restart better!"
        ],
        "analyses": [
            "After a marathon, count 2-3 weeks of complete recovery. Your body underwent enormous stress.",
            "Post-race soreness (DOMS) is normal and can last 3-5 days.",
            "Post-race fatigue is multifactorial: muscular, tendon, immune, mental.",
            "Muscle glycogen takes 24-48h to fully replenish. Eat carbs!",
            "Post-effort inflammation is normal and part of recovery process.",
            "Injury risk is high in the 2 weeks post-race if you restart too fast.",
            "Active recovery (walking, very light cycling) is more effective than total rest.",
            "Your immune system is weakened 24-72h after a long race. Watch for infections.",
            "Pain persisting more than 7 days deserves medical advice.",
            "Mental recovery matters too: savor your performance, even if it wasn't perfect."
        ],
        "conseils": [
            "D+0: Walk 10-15 min, gentle stretching, eat and drink within the hour. Cold bath if possible.",
            "D+1 to D+3: Rest or very light walking/cycling. No running. Keep eating and sleeping well.",
            "D+4 to D+7: Very easy jog 20-30 min if feelings are good. Otherwise, more rest.",
            "D+7 to D+14: Progressive restart, short jogs, no intensity. Listen to your body.",
            "After D+14: If all is well, you can resume normal training progressively.",
            "Drink a lot in following days: hydration helps evacuate metabolic waste.",
            "Foam roller or massage helps accelerate muscle recovery.",
            "Eat proteins for muscle reconstruction, carbs for energy.",
            "Sleep more than usual: that's when recovery happens.",
            "Savor your performance! Take time to celebrate before thinking about the next one."
        ],
        "relances": [
            "What distance was your race?",
            "How do you feel physically?",
            "Where do you have soreness?",
            "Did you eat and drink well after?",
            "Is this your first race at this distance?",
            "How much recovery time did you plan?",
            "Do you have any specific pain?",
            "How was your race? Happy with the result?",
            "Do you already have a next goal in mind?",
            "Can you rest or do you want to run again?"
        ]
    },

    # ==================== CATEGORY 18: GENERAL QUESTIONS ====================
    "general": {
        "keywords": ["conseil", "aide", "quoi", "comment", "pourquoi", "question", "avis", "pense", "sais pas"],
        "intros": [
            "I'm here to help you! 🙌",
            "Good question!",
            "I'll explain!",
            "Let's look at this together!",
            "Here we go!",
            "I'll tell you what I think!",
            "Alright, let's check this!",
            "I'm your coach, ask your questions!",
            "You did well to ask!",
            "Let's see this!"
        ],
        "analyses": [
            "Looking at your recent data, I see that {observation_generale}.",
            "Your regularity ({nb_seances} sessions/week) is {regularite_comment}.",
            "Your current volume ({km_semaine} km) is {volume_comment} for your level.",
            "Your zone distribution shows {zones_comment}.",
            "Your progress these past weeks is {progression_comment}.",
            "Your load/recovery ratio ({ratio}) indicates {ratio_comment}.",
            "Overall, you're on good momentum. {dynamique_detail}",
            "I noticed that {pattern_observe}. It's {pattern_interpretation}.",
            "Compared to your goals, you're {objectif_position}.",
            "What I take from your history: {resume_historique}."
        ],
        "conseils": [
            "My main advice for you right now: {conseil_principal}.",
            "Keep it up, you're on the right track!",
            "Focus on regularity, it's the key to progress.",
            "Don't hesitate to ask more specific questions if you want to go deeper.",
            "I advise you to {recommandation_specifique}.",
            "To progress, {piste_progression}.",
            "A point to improve: {point_amelioration}.",
            "Your priority should be: {priorite}.",
            "If I had to give you one advice: {conseil_unique}.",
            "Stay in tune with your body, it's your best coach!"
        ],
        "relances": [
            "Do you want to talk about a specific topic?",
            "Do you have other questions?",
            "Is there an aspect of your training you want to dig into?",
            "How can I help you further?",
            "Do you want to look at a specific point?",
            "Do you have specific goals right now?",
            "Is something bothering you?",
            "Do you want a plan for the week?",
            "Any pain or discomfort to report?",
            "How do you feel overall?"
        ]
    },

    # ==================== CATEGORY 19: ROUTINE ====================
    "routine": {
        "keywords": ["routine", "habitude", "régularité", "discipline", "régulier", "tenir", "maintenir", "constance"],
        "intros": [
            "Routine is the key! 🔑",
            "Regularity beats intensity!",
            "Creating a habit, important topic!",
            "Consistency is the secret!",
            "Good catch thinking about this!",
            "Routine is your best ally!",
            "Installing a habit, let's talk!",
            "Discipline is built!",
            "Regularity is 80% of success!",
            "Habits make champions!"
        ],
        "analyses": [
            "A habit takes about 21-66 days to install. Patience!",
            "Given your history, you run on average {frequence} times per week. {frequence_comment}",
            "Regularity is more important than intensity to progress long-term.",
            "The most consistent runners progress the most, not the most intense.",
            "Morning running is often easier to maintain: fewer surprises, it's done!",
            "Routine creates automatism. After a few weeks, you won't have to force yourself.",
            "On days you don't feel like it, a short run is better than no run.",
            "Motivation fluctuates, discipline is constant. Build on discipline.",
            "Your brain resists change the first weeks. It's normal, persevere!",
            "A flexible routine (3-4 possible slots/week) is more sustainable than a rigid one."
        ],
        "conseils": [
            "Plan your sessions like important appointments in your calendar.",
            "Prepare your stuff the night before. Fewer obstacles = more chances to go.",
            "Find a training partner, it commits and motivates.",
            "Start small: 2-3 runs per week, then increase progressively.",
            "Morning is often the best slot to install a routine.",
            "Associate your session with a trigger: 'I run after coffee' or 'I run before shower'.",
            "Allow yourself a short run on difficult days. 15 min > 0 min.",
            "Reward yourself after a good week of regularity.",
            "Don't seek motivation, seek discipline. Motivation will follow.",
            "If you miss a session, don't feel guilty. Just resume at next slot."
        ],
        "relances": [
            "Do you run at what time of day?",
            "Can you maintain a regular rhythm?",
            "What sometimes prevents you from running?",
            "Do you prepare your stuff in advance?",
            "Do you run alone or with someone?",
            "Have you tried running in the morning?",
            "Do you set fixed running appointments?",
            "How many sessions do you aim for per week?",
            "Do you have tricks that help you stay regular?",
            "Laziness, does it happen often?"
        ]
    },

    # ==================== CATEGORY 19: IMPROVE PACE ====================
    # Specific to questions "How to improve my pace"
    "ameliorer_allure": {
        "keywords": [],  # Category activated by combined detect_intent
        "intros": [
            "Improve your pace from {allure}/km? That's a great goal! 🎯",
            "Progress from {allure}/km is doable with the right method!",
            "Good question! To go from {allure} to {allure_cible}/km, there are several levers.",
            "Improve your pace from {allure}/km, that's THE goal of many runners!",
            "Ok, let's work on your speed from {allure}/km! 💪",
            "To progress from your current pace ({allure}/km), you need to be smart.",
            "Pace can be worked on! Your {allure}/km can evolve, here's how.",
        ],
        "analyses": [
            "Your current pace of {allure}/km is {allure_comment}. To progress, you need to combine base endurance (80% of volume) and specific work (20%).",
            "To go from {allure} to {allure_cible}/km (your realistic goal), the secret is regularity + patience. Count 2-3 months of structured work.",
            "Pace improvement comes from: 1) More volume in easy endurance, 2) Threshold sessions, 3) Short intervals. With {km_semaine} km/week, {volume_comment}.",
            "Your cadence of {cadence} spm also plays a role. A faster stride (170-180 spm) = less effort at same pace.",
            "To gain 30 sec/km (from {allure} to {allure_cible}), it takes about 3-4 months of structured work. It's not instant but it's lasting!",
            "Your current volume ({km_semaine} km/week) is {volume_comment}. More easy volume = better running economy = faster pace.",
        ],
        "conseils": [
            "Concrete plan to go from {allure} to {allure_cible}/km:\n• 1 threshold session/week (ex: 3x10min at half-marathon pace)\n• 1 short interval session (ex: 8x400m)\n• The rest in easy endurance (Z2)",
            "Start by adding volume in base endurance. Paradoxically, running slower on easy runs will make you faster in races!",
            "Threshold work is THE key for your pace. Do 2x15min or 3x10min at your half-marathon pace, 1x per week.",
            "For {allure}/km → {allure_cible}/km: aim for 10-12 weeks of work with 1 quality session + 2-3 easy runs per week.",
            "Work your VO2max with short intervals (200-400m). It improves your speed ceiling and thus all your paces.",
            "Hills are great for pace: 6-8 x 30sec uphill, recovery downhill. It boosts power without traumatizing legs.",
        ],
        "relances": []  # No follow-ups, we use suggestions
    },

    # ==================== CATEGORY 19b: IMPROVE ENDURANCE ====================
    "ameliorer_endurance": {
        "keywords": [],
        "intros": [
            "Improve your endurance, excellent goal! 🏃",
            "Endurance is the foundation of everything in running!",
            "For more endurance, you need patience but it pays!",
            "Progress in endurance is the best investment!",
        ],
        "analyses": [
            "Endurance is built with volume. Your current volume ({km_semaine} km/week) is {volume_comment}. Increase progressively (+10% max per week).",
            "For more endurance, the key is to run SLOWLY most of the time. 80% of your km should be in Z2 (conversation possible).",
            "Your endurance base develops over weeks and months. No shortcut, but gains are lasting!",
            "Weekly long runs (1h30-2h+) are essential for endurance. You currently do {nb_sorties_longues} per week.",
        ],
        "conseils": [
            "Plan to improve endurance:\n• Increase your volume by 10% per week\n• Add a long run on weekend (1h30 min)\n• Stay in Z2 for 80% of km",
            "The long run is YOUR key session for endurance. Start at 1h15, progressively go up to 2h over 8-10 weeks.",
            "Run slower! If you can't hold a conversation, it's too fast for base endurance.",
            "Add 1 run per week (even 30-40min easy). Total volume matters more than intensity for endurance.",
        ],
        "relances": []
    },

    # ==================== CATEGORY 19c: STRENGTHS ====================
    "points_forts": {
        "keywords": [],
        "intros": [
            "Your strengths, let's see! 💪",
            "What you excel at is important!",
            "Let's analyze your forces!",
            "Your running assets, here they are!",
        ],
        "analyses": [
            "Your current strengths:\n• **Regularity**: {nb_seances} sessions this week, that's {regularite_comment}\n• **Pace**: {allure}/km, {allure_comment}\n• **Cadence**: {cadence} spm, {cadence_comment}",
            "Analyzing your data, your strengths are:\n• Volume: {km_semaine} km/week ({volume_comment})\n• Endurance: {z1z2}% in low zones\n• Regularity: {nb_seances} sessions/week",
            "What stands out from your profile:\n• You run regularly ({nb_seances} sessions/week) ✓\n• Your pace ({allure}/km) is {allure_comment} ✓\n• You manage load well (ratio {ratio}) ✓",
        ],
        "conseils": [
            "Capitalize on your regularity! That's THE foundation of progress in running.",
            "Your main strength: your consistency. Keep running regularly, gains will come.",
            "Your strength: you run! Many give up, you persevere. That's huge.",
            "Strength to exploit: your endurance base. You can start adding specific work.",
        ],
        "relances": []
    },

    # ==================== CATEGORY 19d: WEAKNESSES ====================
    "points_faibles": {
        "keywords": [],
        "intros": [
            "Your areas for improvement, let's look! 🎯",
            "What we can work on together!",
            "Where you can progress, here!",
            "Improvement tracks!",
        ],
        "analyses": [
            "Your areas for improvement:\n• **Zones**: {z1z2}% in endurance (ideal = 80%). {zones_conseil}\n• **Cadence**: {cadence} spm. {cadence_comment}\n• **Volume**: {km_semaine} km/week, {volume_comment}",
            "Analyzing your data, you can progress on:\n• Zone balance: too much Z3 ({z3}%), not enough Z2\n• Progressive volume: +10% max per week\n• Recovery: make sure to sleep well",
            "Points to work on:\n• {point_ameliorer}\n• More time in base endurance (Z2)\n• Technical work (cadence, stride)",
        ],
        "conseils": [
            "To improve your weaknesses, focus on ONE at a time. Too many changes = failure.",
            "Axis #1 to work on: base endurance. More Z2 = better foundation = lasting progress.",
            "Your easiest weakness to fix: zone distribution. Run slower on easy runs!",
            "Advice: don't see these as weaknesses, but as progress opportunities! 🚀",
        ],
        "relances": []
    },

    # ==================== CATEGORY 19e: BASE ENDURANCE ====================
    "endurance_fondamentale": {
        "keywords": [],
        "intros": [
            "Base endurance, THE foundation of everything! 🏃",
            "Z2, let's talk about it! It's crucial.",
            "Base endurance, the pros' secret!",
            "Zone 2 work, excellent topic!",
        ],
        "analyses": [
            "Base endurance (Z2) is running at a pace where you can TALK easily. Your body uses fat as fuel and develops your aerobic base.",
            "Currently, you spend {z1z2}% of your time in Z1-Z2. The ideal to progress = 80% in easy endurance, 20% in intensity.",
            "Z2 is the pace that feels 'too easy'. But that's where deep adaptations are built: capillaries, mitochondria, running economy.",
            "Your Z2 pace should be around {allure_z2}/km (30-60 sec slower than your average pace). If you're breathing hard, it's too fast!",
        ],
        "conseils": [
            "To work on base endurance:\n• Run at a pace where you can hold a conversation\n• Aim for 70-75% of your max HR\n• Don't look at pace, focus on feel\n• 1h minimum for optimal effects",
            "Z2 trick: run with someone and chat. If you can't talk = too fast. It's the simplest test!",
            "Add a long Z2 run on weekend (1h15-1h30). That's THE key session to develop your endurance.",
            "The trap: running too fast thinking you're in Z2. Check with a heart rate monitor: stay under 75% of your max HR.",
            "Base endurance is frustrating at first (feeling of not progressing). But after 2-3 months, the gains are enormous!",
        ],
        "relances": []
    },

    # ==================== CATEGORY 19f: GENERAL IMPROVEMENT ====================
    "ameliorer_general": {
        "keywords": [],
        "intros": [
            "You want to progress, that's great! 💪",
            "Improve your performance, let's see this together!",
            "Progress is my domain! Let's look.",
            "Ok, we'll help you progress! 🎯",
        ],
        "analyses": [
            "To progress in running, you need volume (endurance), quality (intervals/threshold) and recovery (rest, sleep).",
            "With your {nb_seances} sessions and {km_semaine} km this week, {analyse_progression}.",
            "Progress comes from regularity above all. Better 3 sessions/week for 6 months than 5 sessions/week for 1 month.",
            "Your body adapts to what you ask of it. To progress, you must vary stimuli: endurance, tempo, VO2max, hills...",
        ],
        "conseils": [
            "The 3 pillars of progress:\n• Volume: more km (progressively)\n• Quality: 1-2 specific sessions/week\n• Recovery: rest, sleep, nutrition",
            "To progress, be regular! 3 sessions/week for 3 months beats 5 sessions/week for 1 month.",
            "Add variety: if you always do the same sessions, your body adapts and stagnates.",
            "Patience is key. Real progress takes 3-6 months of constant work.",
        ],
        "relances": []
    },

    # ==================== CATEGORY 19g: SESSION BALANCE (80/20) ====================
    "equilibre_seances": {
        "keywords": [],
        "intros": [
            "The balance between intervals and endurance, great question! ⚖️",
            "The 80/20 ratio, let's talk!",
            "How to distribute your sessions, that's THE key question!",
            "Polarized training, excellent topic!",
        ],
        "analyses": [
            "The golden rule = **80/20**:\n• 80% of volume in easy endurance (Z1-Z2)\n• 20% in intensity (intervals, threshold, VO2max)\n\nYou currently: {z1z2}% in endurance, {z4z5}% in intensity.",
            "With {nb_seances} sessions/week, here's an ideal distribution:\n• 2-3 easy sessions (endurance)\n• 1-2 quality sessions (intervals or threshold)\n• 0-1 long run",
            "Classic mistake: too many sessions in zone 3 (tempo). It's the 'gray zone' - not easy enough to recover, not hard enough to progress.",
            "The polarized model (very easy OR very hard sessions, little middle ground) is proven most effective to progress.",
        ],
        "conseils": [
            "Recommended distribution for {nb_seances} sessions/week:\n• {nb_seances_faciles} sessions in easy endurance (Z2)\n• {nb_seances_qualite} quality session(s) (intervals/threshold)\n• 1 long run if possible",
            "Example balanced week:\n• Monday: Rest\n• Tuesday: Short intervals (8x400m)\n• Wednesday: Easy jog 45min\n• Thursday: Rest or recovery jog\n• Friday: Threshold (3x10min)\n• Saturday: Easy jog\n• Sunday: Long run 1h30",
            "The 'no pain no gain' trap: running hard every time = chronic fatigue + stagnation. Easy runs are ALSO important!",
            "To respect 80/20: use a heart rate monitor and force yourself to stay in Z2 on easy runs. It's counter-intuitive but it works!",
            "If you do 3 sessions/week: 2 easy + 1 quality. If you do 5 sessions/week: 3-4 easy + 1-2 quality. Never exceed 20% intensity!",
        ],
        "relances": []
    },

    # ==================== CATEGORY 20: FALLBACK ====================
    "fallback": {
        "keywords": [],  # No keywords, it's the fallback
        "intros": [
            "Hmm, I'm not sure I understand... 🤔",
            "I don't quite see what you mean...",
            "I'm not getting it, sorry!",
            "Not sure I'm following...",
            "I'm having trouble understanding your question...",
            "Oops, I didn't quite catch that...",
            "Wait, what's your exact question?",
            "I'm a bit lost here...",
            "Can you tell me more?",
            "I don't really understand what you mean..."
        ],
        "analyses": [
            "I'm your running coach, tell me what's bothering you about running!",
            "Talk to me about your training, that's what I'm here for!",
            "On the running side, I can help you with lots of topics.",
            "My domain is running, ask me your questions about that!",
            "I'm knowledgeable about everything related to endurance and running.",
            "For running, I'm your guy! Other things... less so.",
            "My specialty is helping you progress in running.",
            "I didn't understand but tell me what's concerning you training-wise!",
            "Let's talk about your running, that's where I can really help!",
            "Let's refocus on running, that's where I can really help!"
        ],
        "conseils": [
            "Try asking me a question about your training, your form, or your goals!",
            "Ask me for a weekly plan, I handle that!",
            "Talk to me about your feelings, I can analyze!",
            "Want to talk about your last run?",
            "Ask me a question about your next race!",
            "We can talk recovery, nutrition, injuries... whatever you want!",
            "Tell me how you feel, I'll advise you!",
            "Want a summary of your week?",
            "Talk to me about your goals, I'll help you reach them!",
            "What's bothering you running-wise?"
        ],
        "relances": [
            "What exactly did you want to talk about?",
            "Can you clarify your question?",
            "Can you rephrase?",
            "Do you have a question about your training?",
            "How can I help you?",
            "Want to talk about your training?",
            "Is there a running topic that interests you?",
            "Tell me what's on your mind!",
            "What do you need advice on?",
            "What brings you here today?",
            "What do you want to know?",
            "I'm listening, tell me everything!"
        ]
    }
}



# ============================================================
# INTENT DETECTION
# ============================================================

# Short responses that indicate an answer to a previous question
# NOTE: No more "relances" - smart suggestions replace follow-ups
SHORT_RESPONSES = {
    # GREETINGS
    "salut": {
        "response": "Hi! 👋 Good to see you! I'm here to help with your training, recovery, goals...",
    },
    "bonjour": {
        "response": "Good morning! ☀️ Ready to talk running? I can help with your plan, recovery, zones...",
    },
    "hello": {
        "response": "Hello! 👋 I'm your running coach. Tell me what's on your mind!",
    },
    "hey": {
        "response": "Hey! 🙌 What's new running-wise?",
    },
    "coucou": {
        "response": "Hi there! 😊 How's it going? I'm here to help with your training.",
    },
    "bonsoir": {
        "response": "Good evening! 🌙 Want to talk about your training or recovery?",
    },
    "hi": {
        "response": "Hi! 👋 I'm your coach. Talk to me about your training!",
    },
    "yo": {
        "response": "Yo! 🤙 Ready to work?",
    },
    # Time-based responses (morning/evening)
    "matin": {
        "response": "Morning is great for energy and freshness! 🌅 You can plan your intervals in the morning when you're wide awake. For long runs, it leaves the rest of the day free!",
    },
    "soir": {
        "response": "Evening is perfect to decompress after the day! 🌆 Muscles are more flexible and performance is often better. However, avoid too intense sessions just before sleeping.",
    },
    "midi": {
        "response": "Midday is good if you have a long enough break! ☀️ Advantage: it breaks up the day and gives you energy for the afternoon. Just eat light before.",
    },
    # Yes/no responses (French AND English)
    "oui": {
        "response": "Great, let's go! 💪 I'm here to help.",
    },
    "yes": {
        "response": "Great, let's go! 💪 I'm here to help.",
    },
    "ouais": {
        "response": "Perfect! 👊 Let's continue.",
    },
    "yep": {
        "response": "Great! 👍 I'm listening.",
    },
    "non": {
        "response": "No worries, we'll adapt! 👍",
    },
    "no": {
        "response": "No worries, we'll adapt! 👍",
    },
    "nope": {
        "response": "Ok, no problem!",
    },
    "ok": {
        "response": "Perfect! ✅",
    },
    "okay": {
        "response": "Perfect! ✅",
    },
    "d'accord": {
        "response": "Super! 👌",
    },
    "merci": {
        "response": "You're welcome, that's the job! 😊 Happy to help.",
    },
    "thanks": {
        "response": "You're welcome! 😊 That's what I'm here for.",
    },
    "cool": {
        "response": "Glad you like it! 😎",
    },
    "parfait": {
        "response": "Great! We're on the right track. 🎯",
    },
    "perfect": {
        "response": "Great! 🎯",
    },
    "génial": {
        "response": "Glad it suits you! 🙌",
    },
    "top": {
        "response": "Top! 🔥",
    },
    "nickel": {
        "response": "Perfect! 👌",
    },
    # Days of the week
    "lundi": {"response": "Monday, good idea to start the week! 📅 It's often a good day for a recovery session."},
    "mardi": {"response": "Tuesday is often a good day for intervals! 💨 Legs are well recovered from the weekend."},
    "mercredi": {"response": "Wednesday, mid-week, perfect for a quality session! 🎯"},
    "jeudi": {"response": "Thursday, ideal day for a technical session or recovery jog. 🤔"},
    "vendredi": {"response": "Friday, preparing for the weekend! 🏃 Light session to be fresh."},
    "samedi": {"response": "Saturday, ideal day for the long run! ☀️ Take advantage of free time."},
    "dimanche": {"response": "Sunday, classic day for long run or rest! 🌳"},
}


def detect_intent(message: str) -> Tuple[str, float]:
    """Detect the intent/category of the message with understanding of question type"""
    message_lower = message.lower()

    # ============================================================
    # STEP 0: Priority detections BEFORE everything
    # ============================================================

    # Strengths / Weaknesses - personal analysis questions
    if "point fort" in message_lower or "points forts" in message_lower:
        return "points_forts", 0.95
    if "point faible" in message_lower or "points faibles" in message_lower or "point à améliorer" in message_lower:
        return "points_faibles", 0.95

    # Base endurance / Zone 2 - specific question
    if "endurance fondamentale" in message_lower or "zone 2" in message_lower or "z2" in message_lower or "fond " in message_lower:
        return "endurance_fondamentale", 0.95

    # Balance intervals/endurance - question about 80/20 ratio
    equilibre_keywords = ["équilibrer", "equilibrer", "ratio", "répartir", "repartir", "combien de fractionné", "combien de séances", "80/20", "polarisé"]
    types_seances = ["fractionné", "endurance", "séances", "intensité", "qualité", "facile"]
    if any(kw in message_lower for kw in equilibre_keywords) and any(ts in message_lower for ts in types_seances):
        return "equilibre_seances", 0.95

    # ============================================================
    # STEP 1: Detect the TYPE of question (improve, analyze, etc.)
    # ============================================================
    question_type = "general"

    # Detection of "how to improve / progress / work on" questions
    ameliorer_keywords = ["améliorer", "ameliorer", "progresser", "augmenter", "booster", "optimiser", "gagner", "passer de", "passer à", "descendre sous", "baisser mon", "comment aller plus", "courir plus vite", "être plus rapide", "travailler", "développer", "renforcer mon", "augmenter mon"]
    if any(kw in message_lower for kw in ameliorer_keywords):
        question_type = "ameliorer"

    # ============================================================
    # STEP 2: If it's an improvement question, detect the specific SUBJECT
    # ============================================================
    if question_type == "ameliorer":
        # Subject: Pace / Speed
        allure_keywords = ["allure", "pace", "vitesse", "vite", "rapide", "min/km", "km/h", "tempo", "rythme", "chrono"]
        if any(kw in message_lower for kw in allure_keywords):
            return "ameliorer_allure", 0.95

        # Subject: Endurance / Distance
        endurance_keywords = ["endurance", "fond", "longue", "distance", "km", "volume", "tenir plus", "durer"]
        if any(kw in message_lower for kw in endurance_keywords):
            return "ameliorer_endurance", 0.95

        # Subject: Cadence / Stride
        cadence_keywords = ["cadence", "foulée", "spm", "pas"]
        if any(kw in message_lower for kw in cadence_keywords):
            return "ameliorer_allure", 0.95  # Cadence goes with pace

        # General improvement (no specific subject detected)
        return "ameliorer_general", 0.85

    # ============================================================
    # STEP 2b: Detect questions about PROGRESSION / INDICATORS
    # ============================================================
    progression_keywords = ["progress", "indicateur", "surveiller", "mesurer", "savoir si je", "comment voir", "évolue", "évolution", "stagne", "plateau"]
    if any(kw in message_lower for kw in progression_keywords):
        return "progression", 0.90

    # ============================================================
    # STEP 2c: Specific priority detections
    # ============================================================

    # Nutrition / Diet
    nutrition_keywords = ["nutrition", "manger", "alimentation", "glucide", "protéine", "hydrat", "boire", "eau", "gel", "boisson", "repas", "petit-déjeuner", "crampe", "nourrir", "avant la course", "après la course"]
    if any(kw in message_lower for kw in nutrition_keywords):
        return "nutrition", 0.90
    # Préparation course / Compétition
    prepa_keywords = ["course dans", "compétition", "10km", "semi", "marathon", "trail", "dossard", "jour j", "objectif chrono", "préparer une course", "préparer un", "avant ma course"]
    if any(kw in message_lower for kw in prepa_keywords):
        return "prepa_course", 0.90
    
    # Zones cardiaques / Intensité
    zones_keywords = ["zone", "z1", "z2", "z3", "z4", "z5", "intensité", "répartition", "équilibr"]
    if any(kw in message_lower for kw in zones_keywords) and "améliorer" not in message_lower:
        return "zones", 0.90
    
    # Sensations / Bien-être
    sensations_keywords = ["je me sens", "sensation", "comment tu te sens", "forme du jour", "bien aujourd'hui", "mal aujourd'hui", "motivé", "démotivé"]
    if any(kw in message_lower for kw in sensations_keywords):
        return "sensations", 0.85
    
    # ============================================================
    # ÉTAPE 3: Pour les autres questions, détection classique par keywords
    # ============================================================
    best_category = "fallback"
    best_score = 0
    
    for category, data in TEMPLATES.items():
        if category in ["fallback", "ameliorer_allure", "ameliorer_endurance", "ameliorer_general"]:
            continue
            
        keywords = data.get("keywords", [])
        score = 0
        
        for keyword in keywords:
            if keyword in message_lower:
                # Score plus élevé pour les mots exacts
                score += 2
                # Bonus pour les mots en début de message
                if message_lower.startswith(keyword) or message_lower.startswith(keyword[:3]):
                    score += 1
        
        if score > best_score:
            best_score = score
            best_category = category
    
    # Seuil minimum pour éviter les faux positifs
    confidence = min(best_score / 4, 1.0) if best_score > 0 else 0
    
    return best_category, confidence


# ============================================================
# RESPONSE GENERATION (100% deterministic, templates + random)
# ============================================================

def _get_zones_verdict(zones: Dict) -> str:
    """Generate a verdict on zone distribution"""
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    z3 = zones.get("z3", 0)
    z4z5 = zones.get("z4", 0) + zones.get("z5", 0)

    if z1z2 >= 60:
        return "Very good endurance base, keep it up!"
    elif z1z2 >= 40:
        return "Good balance between endurance and intensity."
    elif z3 >= 50:
        return "Lots of tempo, think about doing more base endurance."
    elif z4z5 >= 30:
        return "Quite a bit of intensity! Make sure to recover well."
    else:
        return "Keep varying your sessions!"


def _get_sensations(context: Dict) -> str:
    """Generate a description of feelings based on context"""
    ratio = context.get("ratio", 1.0)
    nb_seances = context.get("nb_seances", 0)
    z4z5 = context.get("zones", {}).get("z4", 0) + context.get("zones", {}).get("z5", 0)

    if ratio > 1.5:
        return "perhaps a bit heavy with this high load"
    elif ratio > 1.2:
        return "decent but monitored given the load"
    elif nb_seances >= 4:
        return "good thanks to your regularity"
    elif z4z5 > 25:
        return "intense with this quality work"
    else:
        return "rather good this week"


def _get_sensations_conseil(context: Dict) -> str:
    """Generate advice based on estimated feelings"""
    ratio = context.get("ratio", 1.0)
    z4z5 = context.get("zones", {}).get("z4", 0) + context.get("zones", {}).get("z5", 0)

    if ratio > 1.5:
        return "Take a cooler week to recover."
    elif ratio > 1.2:
        return "Listen to your body well this week."
    elif z4z5 > 25:
        return "Well done on intensity, recover well between sessions."
    else:
        return "Keep up this momentum!"


def _get_point_fort(context: Dict) -> str:
    """Identify the strong point of the week"""
    zones = context.get("zones", {})
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    nb_seances = context.get("nb_seances", 0)
    cadence = context.get("cadence", 0)

    if nb_seances >= 4:
        return "your regularity"
    elif z1z2 >= 50:
        return "your endurance work"
    elif cadence >= 170:
        return "your running cadence"
    elif context.get("km_semaine", 0) >= 30:
        return "your training volume"
    else:
        return "your motivation to continue"


def _get_point_ameliorer(context: Dict) -> str:
    """Identify the point to improve"""
    zones = context.get("zones", {})
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    z3 = zones.get("z3", 0)
    cadence = context.get("cadence", 0)
    nb_seances = context.get("nb_seances", 0)

    if z1z2 < 30 and z3 > 50:
        return "add more base endurance"
    elif 0 < cadence < 165:
        return "work on your cadence"
    elif nb_seances < 3:
        return "increase session frequency"
    else:
        return "vary session types"


def _get_conseil_semaine_prochaine(context: Dict) -> str:
    """Generate advice for next week"""
    zones = context.get("zones", {})
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    z3 = zones.get("z3", 0)
    ratio = context.get("ratio", 1.0)
    nb_seances = context.get("nb_seances", 0)
    cadence = context.get("cadence", 0)

    conseils = []

    if ratio > 1.3:
        conseils.append("reduce volume a bit to recover better")
    elif ratio < 0.8:
        conseils.append("slightly increase volume")

    if z1z2 < 30 and z3 > 50:
        conseils.append("add a long run in base endurance")

    if 0 < cadence < 165:
        conseils.append("integrate drills or technical work")

    if nb_seances < 3:
        conseils.append("add one more session if your schedule allows")

    if not conseils:
        conseils = [
            "maintain this good balance",
            "continue on this momentum",
            "keep this regularity"
        ]

    return random.choice(conseils) if len(conseils) == 1 else conseils[0]


def _get_resume_global(context: Dict) -> str:
    """Generate a global summary of the week"""
    km = context.get("km_semaine", 0)
    nb = context.get("nb_seances", 0)
    ratio = context.get("ratio", 1.0)

    if nb >= 4 and km >= 30:
        return "very active week"
    elif nb >= 3:
        return "good week"
    elif ratio > 1.3:
        return "loaded week"
    elif nb == 0:
        return "rest week"
    else:
        return "decent week"


def _get_conseil_global(context: Dict) -> str:
    """Generate global advice"""
    zones = context.get("zones", {})
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    ratio = context.get("ratio", 1.0)

    if ratio > 1.3:
        return "Think about recovering well."
    elif z1z2 < 30:
        return "Add more base endurance."
    else:
        return "Keep it up!"


def _get_recup_besoin(context: Dict) -> str:
    """Generate recovery need"""
    ratio = context.get("ratio", 1.0)
    km = context.get("km_semaine", 0)
    nb = context.get("nb_seances", 0)

    if ratio > 1.5:
        return "several days of rest or very light recovery"
    elif ratio > 1.2:
        return "at least 2 days of active recovery"
    elif km >= 40:
        return "1-2 days of active recovery between big sessions"
    elif nb >= 4:
        return "alternate well between effort and recovery"
    else:
        return "maintain a good effort/rest balance"


def _get_recup_conseil(context: Dict) -> str:
    """Generate recovery advice"""
    ratio = context.get("ratio", 1.0)

    conseils = [
        "Hydrate well and sleep enough.",
        "Foam roller can help relax muscles.",
        "A light walk helps active recovery.",
        "Gentle stretching after each run helps.",
        "Sleep is your best ally for recovery."
    ]

    if ratio > 1.3:
        conseils.insert(0, "This week, prioritize rest.")

    return random.choice(conseils)


def _get_allure_comment(context: Dict) -> str:
    """Generate a comment on current pace"""
    allure = context.get("allure", "N/A")
    if allure == "N/A":
        return "no pace data available"

    # Extract minutes and seconds
    try:
        parts = allure.split(":")
        pace_min = float(parts[0]) + float(parts[1]) / 60
    except:
        return "solid"

    if pace_min < 4.5:
        return "really fast, competitor level"
    elif pace_min < 5.0:
        return "very solid, you have a good level"
    elif pace_min < 5.5:
        return "solid, you run well"
    elif pace_min < 6.0:
        return "decent, there's room to improve"
    elif pace_min < 6.5:
        return "average, it's good"
    elif pace_min < 7.0:
        return "decent for a regular runner"
    else:
        return "we can improve this progressively"


def _get_volume_comment(context: Dict) -> str:
    """Generate a comment on training volume"""
    km_semaine = context.get("km_semaine", 0)

    if km_semaine >= 60:
        return "very high, watch recovery"
    elif km_semaine >= 40:
        return "solid for serious preparation"
    elif km_semaine >= 30:
        return "good volume to progress"
    elif km_semaine >= 20:
        return "decent, you can increase progressively"
    elif km_semaine >= 10:
        return "a good start, there's room"
    else:
        return "light, you can add volume if you feel good"


def _get_allure_cible(context: Dict) -> str:
    """Generate a realistic target pace (30 sec/km faster than current)"""
    allure = context.get("allure", "N/A")
    if allure == "N/A":
        return "5:30"

    try:
        parts = allure.split(":")
        pace_min = float(parts[0]) + float(parts[1]) / 60
        # Target = 30 sec/km faster
        target_pace = pace_min - 0.5
        target_min = int(target_pace)
        target_sec = int((target_pace - target_min) * 60)
        return f"{target_min}:{target_sec:02d}"
    except:
        return "5:30"


def _get_analyse_progression(context: Dict) -> str:
    """Generate a progress analysis based on data"""
    km_semaine = context.get("km_semaine", 0)
    nb_seances = context.get("nb_seances", 0)
    zones = context.get("zones", {})
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)

    if nb_seances >= 4 and z1z2 >= 50:
        return "you have a good base, you can aim for more specific work"
    elif nb_seances >= 3:
        return "you have regularity, we can increase intensity"
    elif km_semaine >= 20:
        return "your volume is decent, add variety"
    else:
        return "you're starting well, priority is regularity"


def _get_temps_estime(context: Dict) -> str:
    """Estimate a race time based on current pace"""
    allure = context.get("allure", "N/A")
    if allure == "N/A":
        return "to be determined"

    try:
        parts = allure.split(":")
        pace_min = float(parts[0]) + float(parts[1]) / 60

        # 10km estimation (pace + 5% margin)
        time_10k = pace_min * 10 * 1.05
        hours = int(time_10k // 60)
        minutes = int(time_10k % 60)

        if hours > 0:
            return f"{hours}h{minutes:02d}"
        else:
            return f"{minutes} min"
    except:
        return "to calculate"


def _get_charge_comment(context: Dict) -> str:
    """Generate a comment on training load"""
    km_semaine = context.get("km_semaine", 0)

    if km_semaine >= 50:
        return "solid, be careful not to overload before the race"
    elif km_semaine >= 35:
        return "good for serious prep"
    elif km_semaine >= 25:
        return "decent, you can still increase if you feel good"
    elif km_semaine >= 15:
        return "a good start, keep building your base"
    else:
        return "light, increase progressively"


def _get_duree_totale(context: Dict) -> str:
    """Calculate total running duration for the week"""
    workouts = context.get("recent_workouts", [])
    total_min = sum(w.get("duration_min", 0) for w in workouts)

    if total_min >= 60:
        hours = total_min // 60
        mins = total_min % 60
        return f"{hours}h{mins:02d}"
    else:
        return f"{total_min} min"


def _get_allure_z2(context: Dict) -> str:
    """Calculate Z2 pace (about 45 sec slower than average pace)"""
    allure = context.get("allure", "N/A")
    if allure == "N/A":
        return "7:00-7:30"

    try:
        parts = allure.split(":")
        pace_min = float(parts[0]) + float(parts[1]) / 60
        # Z2 = about 45 sec/km slower
        z2_pace = pace_min + 0.75
        z2_min = int(z2_pace)
        z2_sec = int((z2_pace - z2_min) * 60)
        return f"{z2_min}:{z2_sec:02d}"
    except:
        return "7:00-7:30"


def fill_template(template: str, context: Dict) -> str:
    """Fill a template with context data"""
    # Créer un dictionnaire de remplacement avec des valeurs par défaut
    replacements = {
        "km_semaine": str(context.get("km_semaine", 0)),
        "nb_seances": str(context.get("nb_seances", 0)),
        "allure": context.get("allure", "N/A"),
        "cadence": str(context.get("cadence", 0)),
        "ratio": str(context.get("ratio", 1.0)),
        "charge": str(context.get("charge", 0)),
        "decrochage": str(random.randint(5, 15)),
        "jours_course": str(context.get("jours_course", "N/A")),
        "z1z2": str(context.get("zones", {}).get("z1", 0) + context.get("zones", {}).get("z2", 0)),
        "z3": str(context.get("zones", {}).get("z3", 0)),
        "z4z5": str(context.get("zones", {}).get("z4", 0) + context.get("zones", {}).get("z5", 0)),
        "km_total": str(context.get("km_total", 0)),
        
        # Commentaires contextuels
        "cadence_comment": "c'est dans la bonne zone !" if context.get("cadence", 170) >= 170 else "c'est un peu bas, on peut améliorer ça.",
        "ratio_comment": "c'est équilibré, nickel !" if context.get("ratio", 1.0) <= 1.2 else "c'est un peu élevé, pense à récupérer.",
        "allure_comment": _get_allure_comment(context),
        "volume_comment": _get_volume_comment(context),
        "allure_cible": _get_allure_cible(context),
        "analyse_progression": _get_analyse_progression(context),
        "nb_sorties_longues": str(len([w for w in context.get("recent_workouts", []) if w.get("duration_min", 0) >= 75])),
        "appreciation": "Belle semaine !" if context.get("nb_seances", 0) >= 3 else "C'est un bon début !",
        
        # Sensations (basées sur le ratio et le volume)
        "sensations": _get_sensations(context),
        "sensations_conseil": _get_sensations_conseil(context),
        
        # Comparaison semaine
        "comparaison_km": "stable" if context.get("ratio", 1.0) <= 1.1 else ("en hausse" if context.get("ratio", 1.0) > 1.1 else "en baisse"),
        "comparaison_intensite": "similaire" if context.get("zones", {}).get("z4", 0) + context.get("zones", {}).get("z5", 0) < 20 else "plus intense",
        
        # Charge et évolution
        "charge_niveau": "modérée" if context.get("ratio", 1.0) <= 1.2 else "élevée",
        "charge_interpretation": "tu peux continuer comme ça" if context.get("ratio", 1.0) <= 1.2 else "attention à bien récupérer",
        "allure_evolution": "stable" if context.get("ratio", 1.0) <= 1.1 else "en progression",
        
        # Régularité et répartition
        "nb_jours": str(context.get("nb_seances", 0)),
        "regularite_comment": "Bonne régularité !" if context.get("nb_seances", 0) >= 3 else "Tu peux ajouter une séance si tu te sens bien.",
        "repartition_types": "équilibrée" if context.get("zones", {}).get("z2", 0) > 30 else "orientée intensité",
        "repartition_verdict": "Continue comme ça !" if context.get("zones", {}).get("z2", 0) > 30 else "Ajoute plus d'endurance fondamentale.",
        
        # Points forts/faibles
        "point_fort": _get_point_fort(context),
        "point_ameliorer": _get_point_ameliorer(context),
        
        # Conseil semaine prochaine
        "conseil_semaine_prochaine": _get_conseil_semaine_prochaine(context),
        
        # Résumé global
        "resume_global": _get_resume_global(context),
        "conseil_global": _get_conseil_global(context),
        
        # Récupération
        "recup_besoin": _get_recup_besoin(context),
        "recup_conseil": _get_recup_conseil(context),
        
        # Commentaires contextuels supplémentaires
        "zones_resume": f"Z1-Z2: {context.get('zones', {}).get('z1', 0) + context.get('zones', {}).get('z2', 0)}%, Z3: {context.get('zones', {}).get('z3', 0)}%, Z4-Z5: {context.get('zones', {}).get('z4', 0) + context.get('zones', {}).get('z5', 0)}%" if context.get("zones") else "pas de données de zones",
        "zones_conseil": "bon équilibre !" if context.get("zones", {}).get("z2", 0) > 40 else "pense à faire plus d'endurance fondamentale.",
        "zones_verdict": _get_zones_verdict(context.get("zones", {})),
        "charge_recommandation": "tu peux maintenir ou légèrement augmenter" if context.get("ratio", 1.0) <= 1.2 else "calme un peu le jeu cette semaine",
        "adaptation_comment": "c'est une bonne base à maintenir" if context.get("km_semaine", 0) > 0 else "on démarre doucement",
        "repartition": "correcte" if context.get("zones", {}).get("z2", 0) > 30 else "à ajuster",
        "repartition_comment": "Continue comme ça !",
        "ratio_implication": "tu peux y aller" if context.get("ratio", 1.0) <= 1.2 else "récupère un peu d'abord",
        "progression": "une bonne régularité" if context.get("nb_seances", 0) >= 2 else "une marge de progression",
        "progression_action": "consolider cette base" if context.get("nb_seances", 0) >= 2 else "augmenter le volume progressivement",
        
        # Allure Z2 (environ 45 sec plus lent que l'allure moyenne)
        "allure_z2": _get_allure_z2(context),
        
        # Répartition des séances
        "nb_seances_faciles": str(max(context.get("nb_seances", 3) - 1, 1)),
        "nb_seances_qualite": "1" if context.get("nb_seances", 3) <= 4 else "2",
        
        # Variables pour prépa course (fallback values)
        "distance": context.get("goal_distance", "ta course"),
        "phase_prepa": "d'entraînement" if (context.get("jours_course") or 30) > 14 else "d'affûtage",
        "phase_conseil": "Continue le travail spécifique." if (context.get("jours_course") or 30) > 14 else "Réduis le volume, maintiens l'intensité.",
        "temps_estime": _get_temps_estime(context),
        "charge_comment": _get_charge_comment(context),
        "zones_analyse": "une bonne base d'endurance" if context.get("zones", {}).get("z2", 0) > 40 else "beaucoup de tempo",
        "zones_recommandation": "Continue comme ça !" if context.get("zones", {}).get("z2", 0) > 40 else "Ajoute plus d'endurance fondamentale.",
        
        # Variables génériques
        "duree_totale": _get_duree_totale(context),
        "km_moyenne": str(round(context.get("km_semaine", 0) / max(context.get("nb_seances", 1), 1), 1)),
    }
    
    # Remplacer les placeholders
    result = template
    for key, value in replacements.items():
        result = result.replace("{" + key + "}", value)
    
    # Nettoyer les placeholders non remplacés
    import re
    result = re.sub(r'\{[^}]+\}', '', result)
    
    return result


def generate_response(message: str, context: Dict, category: str = None) -> str:
    """Génère une réponse complète basée sur le message et le contexte"""
    
    # D'abord, vérifier si c'est une réponse courte (réponse à une question précédente)
    message_lower = message.lower().strip()
    
    # Vérifier les réponses courtes connues
    for key, response_data in SHORT_RESPONSES.items():
        if message_lower == key or message_lower.startswith(key + " ") or message_lower.endswith(" " + key):
            return f"{response_data['response']}\n\n{response_data['relance']}"
    
    # Si le message est très court (< 15 caractères) et pas reconnu, être plus accueillant
    if len(message_lower) < 15 and not any(kw in message_lower for cat in TEMPLATES.values() for kw in cat.get("keywords", [])):
        # Réponse générique pour les messages courts non reconnus
        short_responses = [
            f"J'ai pas bien compris \"{message}\" 🤔 Tu peux me donner plus de détails ?",
            f"Hmm, \"{message}\"... tu veux dire quoi exactement ?",
            f"Je suis pas sûr de comprendre. Tu parles de ton entraînement ?",
            f"Peux-tu préciser un peu ? Je suis là pour t'aider sur la course ! 🏃",
        ]
        return random.choice(short_responses)
    
    # Détection d'intention si pas de catégorie fournie
    if not category:
        category, confidence = detect_intent(message)
    
    # Récupérer les templates de la catégorie
    templates = TEMPLATES.get(category, TEMPLATES["fallback"])
    
    # Sélection aléatoire de chaque bloc (SANS les relances)
    intro = random.choice(templates["intros"])
    analyse = random.choice(templates["analyses"])
    conseil = random.choice(templates["conseils"])
    # NOTE: Plus de relance - les suggestions remplacent les relances
    
    # Remplir les templates avec le contexte
    intro = fill_template(intro, context)
    analyse = fill_template(analyse, context)
    conseil = fill_template(conseil, context)
    
    # Ajouts conditionnels
    extras = []
    
    # Si ratio élevé, insister sur la récup
    if context.get("ratio", 1.0) > 1.5:
        extras.append("⚠️ Attention, ton ratio charge/récup est élevé. Priorise le repos cette semaine !")
    
    # Si cadence basse
    if 0 < context.get("cadence", 180) < 165:
        extras.append("💡 Ta cadence est un peu basse. Pense aux gammes et aux côtes pour l'améliorer naturellement.")
    
    # Si course proche
    if context.get("jours_course") and context["jours_course"] <= 14:
        objectif = context.get("objectif_nom", "ta course")
        extras.append(f"🎯 Plus que {context['jours_course']} jours avant {objectif} ! On est dans la dernière ligne droite.")
    
    # Assemblage final (SANS relance à la fin)
    parts = [intro, "", analyse]
    
    if extras:
        parts.extend(["", " ".join(extras)])
    
    parts.extend(["", conseil])
    
    # RAG: Intégrer un tip de la knowledge base si disponible
    rag_tips = context.get("rag_tips", [])
    if rag_tips:
        # Sélectionner un tip pertinent et l'intégrer
        tip = random.choice(rag_tips)
        parts.extend(["", f"💡 {tip}"])
    
    return "\n".join(parts).strip()


# ============================================================
# SUGGESTIONS INTELLIGENTES (Questions que l'USER peut poser au COACH)
# 3-5 questions par réponse, personnalisées avec les données user
# ============================================================

SUGGESTED_QUESTIONS = {
    # ==================== FATIGUE / LOURDEUR ====================
    "fatigue": [
        "Comment mieux récupérer demain ?",
        "Conseils pour éviter la lourdeur en fin de sortie ?",
        "Comment gérer une charge élevée comme celle-là ?",
        "Quel type de footing pour recharger les batteries ?",
        "Comment savoir si je suis en surcharge ?",
        "Quels signes de fatigue surveiller ?",
        "Combien de jours de repos après une grosse semaine ?",
        "Comment optimiser mon sommeil pour mieux récupérer ?",
        "Quelle nutrition pour mieux récupérer ?",
        "Est-ce que je dois réduire le volume cette semaine ?",
        "Comment éviter le surentraînement ?",
        "Quels étirements pour soulager les jambes lourdes ?",
    ],
    
    # ==================== ALLURE / CADENCE ====================
    "allure_cadence": [
        "Comment augmenter ma cadence efficacement ?",
        "Quels drills pour booster ma foulée ?",
        "Quelle allure cible pour mon prochain tempo ?",
        "Comment progresser sur mon allure moyenne ?",
        "Comment améliorer ma technique de course ?",
        "Quels exercices pour une foulée plus économe ?",
        "Comment trouver ma bonne allure en endurance ?",
        "Quelle cadence viser pour progresser ?",
        "Comment travailler ma vitesse sans me blesser ?",
        "Quels gammes faire avant une séance rapide ?",
        "Comment interpréter mes zones cardiaques ?",
        "Quelle est l'allure idéale pour une sortie longue ?",
    ],
    
    # ==================== PLAN / PRÉPA COURSE ====================
    "plan": [
        "Quel plan pour la semaine prochaine ?",
        "Comment augmenter le volume sans risque ?",
        "Comment adapter le plan si je me sens fatigué ?",
        "Combien de séances par semaine idéalement ?",
        "Comment équilibrer fractionné et endurance ?",
        "Quelle progression de volume est sécuritaire ?",
        "Comment planifier une semaine type ?",
        "Quand placer ma sortie longue dans la semaine ?",
        "Comment intégrer du renforcement musculaire ?",
        "Quelle est la meilleure répartition des séances ?",
        "Comment gérer une semaine chargée au travail ?",
        "Quand faire une semaine de récupération ?",
    ],
    
    # ==================== PRÉPA COURSE (proche) ====================
    "prepa_course": [
        "Comment bien préparer ma course ?",
        "Quelle stratégie d'allure adopter ?",
        "Que manger avant la course ?",
        "Comment gérer le stress d'avant-course ?",
        "Quoi faire la dernière semaine avant ?",
        "Comment m'échauffer le jour J ?",
        "Quelle stratégie pour les ravitaillements ?",
        "Comment éviter de partir trop vite ?",
        "Quels objectifs réalistes me fixer ?",
        "Comment gérer le dénivelé sur ce parcours ?",
        "Que faire si je me sens pas bien le jour J ?",
        "Comment récupérer après la course ?",
    ],
    
    # ==================== RÉCUPÉRATION / REPOS ====================
    "recuperation": [
        "Conseils pour mieux dormir et récupérer ?",
        "Comment optimiser ma récup après une semaine chargée ?",
        "Quelle séance de mobilité ajouter ?",
        "Est-ce que je dois prendre un jour off complet ?",
        "Quels étirements faire après une sortie ?",
        "Comment utiliser le foam roller efficacement ?",
        "Bain froid ou chaud pour la récup ?",
        "Quelle alimentation favorise la récupération ?",
        "Comment savoir si j'ai bien récupéré ?",
        "Combien de temps entre deux séances intenses ?",
        "Comment récupérer d'une course difficile ?",
        "Quels compléments pour mieux récupérer ?",
    ],
    
    # ==================== ANALYSE SEMAINE ====================
    "analyse_semaine": [
        "Comment interpréter mes stats de la semaine ?",
        "Est-ce que ma répartition de zones est bonne ?",
        "Comment améliorer ma régularité ?",
        "Qu'est-ce que je pourrais faire mieux ?",
        "Comment comparer avec la semaine dernière ?",
        "Mon volume est-il suffisant pour progresser ?",
        "Comment lire mon ratio charge/récup ?",
        "Quels sont mes points forts actuels ?",
        "Sur quoi devrais-je travailler en priorité ?",
        "Ma progression est-elle normale ?",
        "Comment atteindre mes objectifs plus vite ?",
        "Quelles erreurs éviter pour la suite ?",
    ],
    
    # ==================== MOTIVATION ====================
    "motivation": [
        "Comment rester motivé sur la durée ?",
        "Petit défi fun pour la prochaine sortie ?",
        "Comment gérer les baisses de motivation ?",
        "Quoi faire quand j'ai pas envie de courir ?",
        "Comment me fixer des objectifs motivants ?",
        "Comment varier mes parcours pour pas m'ennuyer ?",
        "Courir seul ou en groupe, qu'est-ce qui est mieux ?",
        "Comment transformer une mauvaise sortie en positif ?",
        "Comment célébrer mes petites victoires ?",
        "Comment garder l'envie après un échec ?",
        "Quels podcasts ou musiques pour courir ?",
        "Comment me remotiver après une pause ?",
    ],
    
    # ==================== BLESSURES ====================
    "blessures": [
        "Que faire pour une douleur au genou ?",
        "Dois-je continuer ou me reposer avec cette douleur ?",
        "Conseils pour éviter que ça empire ?",
        "Quels exercices de renforcement préventif ?",
        "Comment reprendre après une blessure ?",
        "Quand consulter un médecin du sport ?",
        "Comment prévenir les blessures courantes ?",
        "Quels signes indiquent qu'il faut s'arrêter ?",
        "Comment adapter mon entraînement avec une gêne ?",
        "Quels étirements pour prévenir les douleurs ?",
        "Comment renforcer mes points faibles ?",
        "Quelle est la différence entre courbature et blessure ?",
    ],
    
    # ==================== PROGRESSION / STAGNATION ====================
    "progression": [
        "Comment casser un plateau de progression ?",
        "Pourquoi je ne progresse plus ?",
        "Comment varier mes entraînements pour progresser ?",
        "Quelle est ma VMA estimée ?",
        "Comment travailler ma vitesse efficacement ?",
        "Quels types de séances pour progresser vite ?",
        "Comment savoir si je progresse vraiment ?",
        "Quel volume pour passer au niveau supérieur ?",
        "Comment améliorer mon endurance fondamentale ?",
        "Quels indicateurs de progression surveiller ?",
        "Comment éviter de stagner dans mon entraînement ?",
        "Quels objectifs intermédiaires me fixer ?",
    ],
    
    # ==================== NUTRITION ====================
    "nutrition": [
        "Quoi manger avant une sortie longue ?",
        "Comment bien m'hydrater pendant l'effort ?",
        "Quels gels ou barres recommandes-tu ?",
        "Comment éviter les problèmes digestifs en courant ?",
        "Que manger après une séance intense ?",
        "Comment adapter mon alimentation à mon entraînement ?",
        "Quels aliments favorisent la récupération ?",
        "Comment gérer la nutrition en course longue ?",
        "Petit-déjeuner idéal avant une course ?",
        "Comment éviter les crampes ?",
        "Faut-il prendre des compléments alimentaires ?",
        "Combien boire par jour quand on s'entraîne ?",
    ],
    
    # ==================== ÉQUIPEMENT ====================
    "equipement": [
        "Quand changer mes chaussures de running ?",
        "Comment choisir ma prochaine paire de chaussures ?",
        "Quel équipement pour courir sous la pluie ?",
        "Comment éviter les ampoules ?",
        "Quelle montre GPS recommandes-tu ?",
        "Quels vêtements techniques privilégier ?",
        "Comment entretenir mes chaussures de running ?",
        "Quel équipement pour le trail ?",
        "Comment choisir mes chaussettes de course ?",
        "Faut-il des chaussures différentes selon le terrain ?",
        "Comment habiller pour courir par grand froid ?",
        "Quels accessoires vraiment utiles pour courir ?",
    ],
    
    # ==================== GÉNÉRAL / FALLBACK ====================
    "general": [
        "Analyse ma dernière sortie ?",
        "Conseil pour ma récup globale ?",
        "Plan pour la semaine prochaine ?",
        "Comment progresser sur mon allure ?",
        "Comment améliorer ma technique de course ?",
        "Quels objectifs me fixer ?",
        "Comment équilibrer vie perso et entraînement ?",
        "Quels sont mes axes de progression ?",
        "Comment me préparer pour ma prochaine course ?",
        "Comment interpréter mes données d'entraînement ?",
        "Quels conseils pour un coureur de mon niveau ?",
        "Comment structurer ma semaine d'entraînement ?",
    ],
    
    # ==================== FALLBACK ====================
    "fallback": [
        "Comment améliorer ma récup ?",
        "Plan pour la semaine prochaine ?",
        "Comment progresser en course à pied ?",
        "Analyse de ma dernière séance ?",
        "Conseils pour éviter les blessures ?",
        "Comment augmenter mon volume ?",
        "Quelle séance faire demain ?",
        "Comment améliorer ma cadence ?",
        "Quels exercices de renforcement faire ?",
        "Comment mieux gérer mes zones cardiaques ?",
        "Conseils nutrition pour coureur ?",
        "Comment rester motivé ?",
    ],
}

# Mapping des catégories vers leurs suggestions
CATEGORY_SUGGESTION_MAP = {
    "fatigue": "fatigue",
    "allure_cadence": "allure_cadence",
    "recuperation": "recuperation",
    "plan": "plan",
    "prepa_course": "prepa_course",
    "analyse_semaine": "analyse_semaine",
    "motivation": "motivation",
    "blessures": "blessures",
    "progression": "progression",
    "nutrition": "nutrition",
    "equipement": "equipement",
    "meteo": "general",
    "mental": "motivation",
    "sommeil": "recuperation",
    "renforcement": "blessures",
    "chaleur": "general",
    "post_course": "recuperation",
    "habitudes": "general",
    "general": "general",
    "fallback": "fallback",
}


def get_personalized_suggestions(category: str, context: Dict, num_suggestions: int = 4) -> List[str]:
    """
    Génère 3-5 suggestions personnalisées (questions que l'USER peut poser au COACH).
    Personnalise avec les données user quand disponibles.
    """
    # Récupérer la catégorie de suggestions
    suggestion_category = CATEGORY_SUGGESTION_MAP.get(category, "fallback")
    base_suggestions = SUGGESTED_QUESTIONS.get(suggestion_category, SUGGESTED_QUESTIONS["fallback"])
    
    # Créer une liste de suggestions personnalisées
    personalized = []
    
    # Extraire le contexte utilisateur
    jours_course = context.get("jours_course")
    objectif = context.get("objectif_nom", "")
    cadence = context.get("cadence", 0)
    ratio = context.get("ratio", 1.0)
    km_semaine = context.get("km_semaine", 0)
    nb_seances = context.get("nb_seances", 0)
    allure = context.get("allure", "")
    zones = context.get("zones", {})
    
    # Suggestions personnalisées basées sur le contexte
    
    # Si course proche avec objectif défini
    if jours_course and jours_course > 0 and jours_course <= 30:
        if objectif:
            personalized.append(f"Comment bien préparer {objectif} ?")
            if jours_course <= 7:
                personalized.append(f"Quoi faire cette dernière semaine avant {objectif} ?")
            elif jours_course <= 14:
                personalized.append(f"Comment gérer les {jours_course} derniers jours avant {objectif} ?")
        else:
            personalized.append(f"Comment préparer ma course dans {jours_course} jours ?")
    
    # Si cadence basse (< 165)
    if 0 < cadence < 165:
        personalized.append("Comment améliorer ma cadence de course ?")
        personalized.append("Quels drills pour augmenter ma cadence ?")
    
    # Si ratio élevé (surcharge)
    if ratio > 1.3:
        personalized.append("Comment mieux récupérer cette semaine ?")
        personalized.append("Dois-je réduire le volume ?")
    
    # Si beaucoup de Z3 (tempo) et peu de Z1-Z2 (endurance)
    z1z2 = zones.get("z1", 0) + zones.get("z2", 0)
    z3 = zones.get("z3", 0)
    if z3 > 50 and z1z2 < 30:
        personalized.append("Comment équilibrer mes zones d'entraînement ?")
        personalized.append("Comment travailler plus en endurance fondamentale ?")
    
    # Si volume élevé
    if km_semaine >= 40:
        personalized.append("Comment maintenir ce volume sans me blesser ?")
    
    # Si peu de séances
    if 0 < nb_seances < 3:
        personalized.append("Comment optimiser avec peu de séances par semaine ?")
    
    # Si allure connue
    if allure and allure != "N/A":
        personalized.append(f"Comment améliorer mon allure de {allure}/km ?")
    
    # Compléter avec des suggestions de base (randomisées)
    remaining_needed = num_suggestions - len(personalized)
    if remaining_needed > 0:
        # Filtrer les suggestions déjà ajoutées
        available = [s for s in base_suggestions if s not in personalized]
        random.shuffle(available)
        personalized.extend(available[:remaining_needed])
    
    # Limiter à num_suggestions et mélanger
    result = personalized[:num_suggestions]
    random.shuffle(result)
    
    return result
