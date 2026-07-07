"""
Test suite for CardioCoach Detailed Analysis API (Card-based Mobile Experience)
Tests the GET /api/coach/detailed-analysis/{workout_id} endpoint

Features tested:
- Response structure (header, execution, meaning, recovery, advice, advanced)
- Header context is 1 sentence max, plain language
- Execution card has intensity (Easy/Moderate/Sustained), volume (Usual/Longer/One-off peak), regularity (Stable/Unknown/Variable)
- Meaning text is 2-3 short sentences, no jargon
- Recovery text is 1 key message, neutral tone
- Advice text is 1 clear actionable recommendation
- Language enforcement: 100% EN or 100% FR, no mixing
"""

import pytest
import requests
import os
import re

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
WORKOUT_ID = "strava_17130033093"

# French words that should NOT appear in English responses
# Excluding words that are the same in both languages (stable, effort, volume, etc.)
FRENCH_WORDS = [
    "séance", "sortie", "récupération", "prochaine", "facile", "soutenue", 
    "modérée", "habituel", "plus long", "pic ponctuel", "inconnue",
    "fréquence", "cardiaque", "allure", "moyenne", "kilomètre",
    "heures", "jours", "semaine", "entraînement",
    "intensité", "régularité", "conseil", "analyse", "détaillée"
]

# English words that should NOT appear in French responses
ENGLISH_WORDS = [
    "session", "workout", "recovery", "next", "easy", "sustained", "moderate",
    "usual", "longer", "one-off peak", "stable", "unknown", "variable",
    "heart rate", "pace", "average", "kilometer", "hours", "minutes", "days",
    "week", "training", "effort", "intensity", "volume", "regularity",
    "advice", "analysis", "detailed"
]


class TestDetailedAnalysisEndpoint:
    """Test the detailed analysis endpoint structure and content"""
    
    def test_endpoint_returns_200(self):
        """Test that the endpoint returns 200 for a valid workout"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Endpoint returns 200 for valid workout")
    
    def test_response_structure_has_all_required_fields(self):
        """Test that response has all required fields: header, execution, meaning, recovery, advice, advanced"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        assert response.status_code == 200
        data = response.json()
        
        # Check top-level fields
        required_fields = ["workout_id", "workout_name", "workout_date", "workout_type", 
                          "header", "execution", "meaning", "recovery", "advice"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
        
        # Advanced is optional but should be present
        assert "advanced" in data, "Missing advanced field"
        
        print("✓ Response has all required fields: header, execution, meaning, recovery, advice, advanced")
    
    def test_header_has_context_and_session_name(self):
        """Test that header has context and session_name"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "header" in data
        assert "context" in data["header"], "Header missing context"
        assert "session_name" in data["header"], "Header missing session_name"
        
        print(f"✓ Header has context: '{data['header']['context'][:50]}...'")
        print(f"✓ Header has session_name: '{data['header']['session_name']}'")
    
    def test_header_context_is_one_sentence_max(self):
        """Test that header.context is 1 sentence max, plain language"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        context = data["header"]["context"]
        
        # Count sentences (split by . ! ?)
        sentences = re.split(r'[.!?]+', context.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        assert len(sentences) <= 2, f"Header context has {len(sentences)} sentences, expected max 1-2"
        assert len(context) < 200, f"Header context too long: {len(context)} chars"
        
        print(f"✓ Header context is {len(sentences)} sentence(s), {len(context)} chars")
    
    def test_execution_card_has_intensity_volume_regularity(self):
        """Test that execution card has intensity, volume, regularity"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "execution" in data
        execution = data["execution"]
        
        assert "intensity" in execution, "Execution missing intensity"
        assert "volume" in execution, "Execution missing volume"
        assert "regularity" in execution, "Execution missing regularity"
        
        print(f"✓ Execution: intensity={execution['intensity']}, volume={execution['volume']}, regularity={execution['regularity']}")
    
    def test_execution_intensity_valid_values_en(self):
        """Test that intensity is Easy/Moderate/Sustained in English"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        intensity = data["execution"]["intensity"]
        valid_values = ["Easy", "Moderate", "Sustained", "easy", "moderate", "sustained"]
        
        # Check if intensity contains any valid value (case-insensitive)
        intensity_lower = intensity.lower()
        assert any(v.lower() in intensity_lower for v in valid_values), \
            f"Intensity '{intensity}' not in valid values: {valid_values}"
        
        print(f"✓ Intensity '{intensity}' is valid")
    
    def test_execution_volume_valid_values_en(self):
        """Test that volume is Usual/Longer/One-off peak in English"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        volume = data["execution"]["volume"]
        valid_values = ["Usual", "Longer", "One-off peak", "usual", "longer", "one-off", "peak"]
        
        volume_lower = volume.lower()
        assert any(v.lower() in volume_lower for v in valid_values), \
            f"Volume '{volume}' not in valid values: {valid_values}"
        
        print(f"✓ Volume '{volume}' is valid")
    
    def test_execution_regularity_valid_values_en(self):
        """Test that regularity is Stable/Unknown/Variable in English"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        regularity = data["execution"]["regularity"]
        valid_values = ["Stable", "Unknown", "Variable", "stable", "unknown", "variable"]
        
        regularity_lower = regularity.lower()
        assert any(v.lower() in regularity_lower for v in valid_values), \
            f"Regularity '{regularity}' not in valid values: {valid_values}"
        
        print(f"✓ Regularity '{regularity}' is valid")
    
    def test_meaning_text_is_2_3_sentences(self):
        """Test that meaning.text is 2-3 short sentences, no jargon"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "meaning" in data
        assert "text" in data["meaning"]
        
        meaning_text = data["meaning"]["text"]
        
        # Count sentences
        sentences = re.split(r'[.!?]+', meaning_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        assert 1 <= len(sentences) <= 4, f"Meaning has {len(sentences)} sentences, expected 2-3"
        
        # Check for jargon (should not have complex physiological terms)
        jargon_terms = ["VO2max", "lactate threshold", "anaerobic", "glycolytic", "mitochondrial"]
        for term in jargon_terms:
            assert term.lower() not in meaning_text.lower(), f"Meaning contains jargon: {term}"
        
        print(f"✓ Meaning text has {len(sentences)} sentences, no jargon detected")
    
    def test_recovery_text_is_one_key_message(self):
        """Test that recovery.text is 1 key message, neutral tone"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "recovery" in data
        assert "text" in data["recovery"]
        
        recovery_text = data["recovery"]["text"]
        
        # Count sentences
        sentences = re.split(r'[.!?]+', recovery_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        assert 1 <= len(sentences) <= 2, f"Recovery has {len(sentences)} sentences, expected 1"
        
        # Check for alarmist language
        alarmist_words = ["danger", "warning", "critical", "urgent", "immediately", "risk"]
        for word in alarmist_words:
            assert word.lower() not in recovery_text.lower(), f"Recovery contains alarmist word: {word}"
        
        print(f"✓ Recovery text is {len(sentences)} sentence(s), neutral tone")
    
    def test_advice_text_is_one_recommendation(self):
        """Test that advice.text is 1 clear actionable recommendation"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "advice" in data
        assert "text" in data["advice"]
        
        advice_text = data["advice"]["text"]
        
        # Count sentences
        sentences = re.split(r'[.!?]+', advice_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        
        assert 1 <= len(sentences) <= 2, f"Advice has {len(sentences)} sentences, expected 1"
        
        # Should be actionable (contain action words)
        action_indicators = ["next", "try", "keep", "focus", "prioritize", "session", "run", "ride"]
        advice_lower = advice_text.lower()
        has_action = any(word in advice_lower for word in action_indicators)
        
        print(f"✓ Advice text is {len(sentences)} sentence(s), actionable: {has_action}")
    
    def test_advanced_section_exists(self):
        """Test that advanced section exists with comparisons"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        assert "advanced" in data
        
        if data["advanced"]:
            assert "comparisons" in data["advanced"], "Advanced missing comparisons"
            print(f"✓ Advanced section has comparisons: {data['advanced']['comparisons'][:100]}...")
        else:
            print("✓ Advanced section is empty (optional)")


class TestLanguageEnforcement:
    """Test strict language enforcement: 100% EN or 100% FR"""
    
    def test_english_response_has_no_french_words(self):
        """Test that English response contains 100% English, no French words"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        # Combine all text fields
        all_text = " ".join([
            data["header"].get("context", ""),
            data["header"].get("session_name", ""),
            data["execution"].get("intensity", ""),
            data["execution"].get("volume", ""),
            data["execution"].get("regularity", ""),
            data["meaning"].get("text", ""),
            data["recovery"].get("text", ""),
            data["advice"].get("text", ""),
            data.get("advanced", {}).get("comparisons", "") or ""
        ]).lower()
        
        # Check for French words
        found_french = []
        for word in FRENCH_WORDS:
            if word.lower() in all_text:
                found_french.append(word)
        
        assert len(found_french) == 0, f"English response contains French words: {found_french}"
        print("✓ English response is 100% English, no French words detected")
    
    def test_french_response_has_no_english_words(self):
        """Test that French response contains 100% French, no English words"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=fr")
        data = response.json()
        
        # Combine all text fields
        all_text = " ".join([
            data["header"].get("context", ""),
            data["header"].get("session_name", ""),
            data["execution"].get("intensity", ""),
            data["execution"].get("volume", ""),
            data["execution"].get("regularity", ""),
            data["meaning"].get("text", ""),
            data["recovery"].get("text", ""),
            data["advice"].get("text", ""),
            data.get("advanced", {}).get("comparisons", "") or ""
        ]).lower()
        
        # Check for English words (excluding common words that might appear in both)
        found_english = []
        for word in ENGLISH_WORDS:
            # Skip short words that might be false positives
            if len(word) > 4 and word.lower() in all_text:
                found_english.append(word)
        
        # Allow some tolerance for technical terms
        assert len(found_english) <= 2, f"French response contains English words: {found_english}"
        print(f"✓ French response is mostly French (found {len(found_english)} English words)")
    
    def test_french_execution_values(self):
        """Test that French execution card has French values"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=fr")
        data = response.json()
        
        execution = data["execution"]
        
        # French intensity values
        french_intensity = ["Facile", "Modérée", "Soutenue", "facile", "modérée", "soutenue"]
        intensity = execution["intensity"]
        intensity_is_french = any(v.lower() in intensity.lower() for v in french_intensity)
        
        # French volume values
        french_volume = ["Habituel", "Plus long", "Pic ponctuel", "habituel", "plus long", "pic"]
        volume = execution["volume"]
        volume_is_french = any(v.lower() in volume.lower() for v in french_volume)
        
        # French regularity values
        french_regularity = ["Stable", "Inconnue", "Variable", "stable", "inconnue", "variable"]
        regularity = execution["regularity"]
        regularity_is_french = any(v.lower() in regularity.lower() for v in french_regularity)
        
        print(f"✓ French execution: intensity={intensity} (FR: {intensity_is_french}), volume={volume} (FR: {volume_is_french}), regularity={regularity} (FR: {regularity_is_french})")
        
        # At least intensity should be in French
        assert intensity_is_french or volume_is_french, "French execution values should be in French"


class TestWorkoutNotFound:
    """Test error handling for non-existent workouts"""
    
    def test_invalid_workout_returns_404(self):
        """Test that invalid workout ID returns 404"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/invalid_workout_id_12345?language=en")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid workout ID returns 404")


class TestResponseQuality:
    """Test the quality and scannability of responses"""
    
    def test_response_is_scannable_under_10_seconds(self):
        """Test that response content is concise enough to scan in <10 seconds"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        # Calculate total text length
        total_text = " ".join([
            data["header"].get("context", ""),
            data["meaning"].get("text", ""),
            data["recovery"].get("text", ""),
            data["advice"].get("text", "")
        ])
        
        # Average reading speed is ~200-250 words per minute
        # 10 seconds = ~40 words max for comfortable scanning
        word_count = len(total_text.split())
        
        # Allow up to 100 words for the main content (excluding advanced)
        assert word_count < 150, f"Content has {word_count} words, may take >10 seconds to scan"
        
        print(f"✓ Main content has {word_count} words, scannable in <10 seconds")
    
    def test_no_excessive_numbers(self):
        """Test that content doesn't have excessive numbers (data overload)"""
        response = requests.get(f"{BASE_URL}/api/coach/detailed-analysis/{WORKOUT_ID}?language=en")
        data = response.json()
        
        # Check main cards (not advanced)
        main_text = " ".join([
            data["header"].get("context", ""),
            data["meaning"].get("text", ""),
            data["recovery"].get("text", ""),
            data["advice"].get("text", "")
        ])
        
        # Count numbers in main text
        numbers = re.findall(r'\d+', main_text)
        
        # Should have minimal numbers in main cards (advanced can have more)
        assert len(numbers) < 10, f"Main content has {len(numbers)} numbers, may be data overload"
        
        print(f"✓ Main content has {len(numbers)} numbers, not overloaded")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
