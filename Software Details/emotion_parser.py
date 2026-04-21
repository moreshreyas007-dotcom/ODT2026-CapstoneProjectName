# emotion_parser.py
# Reads Claude's emotion tags → returns behavior name + clean text

EMOTION_TO_BEHAVIOR = {
    "[AGREE]":    "nod",
    "[DISAGREE]": "head_shake",
    "[EXCITED]":  "wiggle",
    "[THINK]":    "head_tilt",
    "[IDLE]":     "idle_look",
    "[HAPPY]":    "happy_bounce",
    "[CURIOUS]":  "curious_tilt",
}

DEFAULT_BEHAVIOR = "idle_look"
ALL_TAGS         = list(EMOTION_TO_BEHAVIOR.keys())


class EmotionParser:
    def __init__(self):
        print(" Emotion parser ready")

    def parse(self, text: str) -> tuple[str, str]:
        """
        Input:  "[EXCITED] That's so cool!"
        Output: ("wiggle", "That's so cool!")
        """
        behavior   = DEFAULT_BEHAVIOR
        clean_text = text

        for tag, behavior_name in EMOTION_TO_BEHAVIOR.items():
            if tag in text:
                behavior   = behavior_name
                clean_text = text.replace(tag, "", 1).strip()
                break

        # strip any leftover tags
        for tag in ALL_TAGS:
            clean_text = clean_text.replace(tag, "").strip()

        return behavior, clean_text

    def extract_behavior_only(self, text: str) -> str:
        behavior, _ = self.parse(text)
        return behavior
