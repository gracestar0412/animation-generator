"""Generate battle extension scenes for ch03 (David vs Goliath combat)."""
import asyncio
import json
import os
import re
import sys

# Make sure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROMPT = """You are continuing a Bible animation script for "A Stone and a Sling" (David vs Goliath).

The previous 27 scenes covered: Goliath's challenge, David hearing it, David persuading King Saul to let him fight, David rejecting Saul's armor, and David picking 5 smooth stones from the brook. The last scene (Scene 27, 1 second) was: "With his simple shepherd's tools, David advanced."

NOW WRITE 10 DRAMATIC SCENES (Scene 28-37) covering the CLIMACTIC BATTLE AND VICTORY:
- David walking towards Goliath across the valley (tension building)
- Goliath mocking and cursing David ("Am I a dog that you come at me with sticks?")
- David's bold declaration of faith ("You come with sword and spear, but I come in the name of the Lord of hosts!")
- David running towards Goliath at full speed
- The sling whipping overhead, the stone flying through the air
- The stone striking Goliath's forehead with devastating impact
- Goliath falling face-first to the ground (DRAMATIC slow-motion moment)
- David standing over the fallen giant
- The Philistines fleeing in panic and terror
- Israel's army charging forward with a mighty shout of victory

Each scene: 5-8 seconds MAX, ~15-20 words narration.
Style: Pixar/Disney 3D animation, dramatic cinematic.

CHARACTER DESCRIPTIONS (use these EXACTLY in objects field):
- DAVID: Young shepherd boy (~16), ruddy skin, reddish-brown curly hair, simple wool tunic, leather sling in hand
- GOLIATH: Towering 9-foot Philistine warrior, dark bronze skin, thick black braided beard, bronze scale armor, massive iron-tipped spear

Format as strict JSON list:
[
  {
    "id": 28,
    "narration": "narration text here",
    "duration": 7,
    "characters": ["DAVID", "GOLIATH"],
    "video_prompt": {
      "objects": "character and scene description",
      "action": "what happens in the scene",
      "style": "Pixar/Disney 3D cinematic biblical animation",
      "camera": "shot type and movement",
      "atmosphere": "mood and lighting",
      "sfx": "sound effects",
      "negative": "distorted face, extra limbs, text overlay"
    }
  }
]

IMPORTANT: These scenes are the CLIMAX of the entire David and Goliath story. Make them DRAMATIC, IMPACTFUL, and VISUALLY STUNNING. This is the moment viewers have been waiting for."""


async def main():
    from google import genai

    credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shorts.json")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

    client = genai.Client(vertexai=True, project="rare-style-481210-p3", location="global")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT,
    )
    resp = response.text

    match = re.search(r"\[.*\]", resp, re.DOTALL)
    if match:
        new_scenes = json.loads(match.group())
        print(f"Generated {len(new_scenes)} battle scenes:")
        total_dur = 0
        for s in new_scenes:
            total_dur += s["duration"]
            print(f"  Scene {s['id']} ({s['duration']}s): {s['narration'][:80]}")
        print(f"\nTotal battle duration: {total_dur}s")

        out_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data/projects/david_and_goliath/ch03_a_stone_and_a_sling/battle_scenes.json"
        )
        with open(out_path, "w") as f:
            json.dump(new_scenes, f, ensure_ascii=False, indent=2)
        print(f"Saved to {out_path}")
    else:
        print("Failed to parse JSON from response:")
        print(resp[:2000])


if __name__ == "__main__":
    asyncio.run(main())
