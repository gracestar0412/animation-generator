
import os
import asyncio
from google import genai
from google.genai import types

PROJECT_ID = "rare-style-481210-p3"
CREDS_PATH = "/Users/gracestar/project/animation-generator/shorts.json"

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH

async def main():
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
        print("✅ Client initialized")
        
        # Try listing models first
        try:
             model_name = "veo-3.1-fast-generate-preview" # From shorts-maker
             prompt = "Macro shot of a youtube UI. A cursor clicks a red 'Subscribe' button. It turns gray and says 'Subscribed'. The cursor moves away. The button STAYS gray. No further animation. Ends on static frame of 'Subscribed'. High quality 4k."
             print(f"🎬 Attempting to generate V3 CTA with strict prompt: {prompt}")
             
             # Need to use types.GenerateVideosSource as per shorts-maker
             source = types.GenerateVideosSource(
                 prompt=prompt,
             )

             config = types.GenerateVideosConfig(
                 aspect_ratio="16:9",
                 number_of_videos=1,
                 person_generation="allow_all",
                 duration_seconds=8, # Must be <= 8 for Veo
                 generate_audio=False,
                 resolution="1080p",
             )

             print("🚀 Sending request...")
             # client.models.generate_videos returns an LRO (check shorts-maker)
             operation = await asyncio.to_thread(
                client.models.generate_videos,
                model=model_name, 
                source=source,
                config=config,
            )
             
             print(f"⏳ Waiting for LRO: {getattr(operation, 'name', 'unknown')}")
             
             # simple polling loop
             import time
             while not operation.done:
                 print(".", end="", flush=True)
                 await asyncio.sleep(5)
                 # Refresh operation? client.operations.get(operation.name)?
                 # The returned object might auto-update or need manual refresh
                 # shorts-maker uses client.operations.get(operation)
                 try:
                     operation = await asyncio.to_thread(client.operations.get, operation)
                 except Exception as e:
                     print(f"Polling error: {e}")
                     break

             print("\n✅ Operation done!")
             
             if hasattr(operation, 'error') and operation.error:
                 print(f"❌ Operation Failed: {operation.error}")
             else:
                 result = operation.result
                 if result and result.generated_videos:
                     print("✅ Video generated!")
                     vid = result.generated_videos[0]
                     output_path = "veo_test_video.mp4"
                     if hasattr(vid.video, 'video_bytes'):
                        with open(output_path, "wb") as f:
                            f.write(vid.video.video_bytes)
                     elif hasattr(vid, 'video_bytes'): # sometimes directly on object?
                        with open(output_path, "wb") as f:
                            f.write(vid.video_bytes)
                     else:
                         print(f"⚠️ Video structure unclear: {dir(vid)}")
                         # Try saving via save() if available
                         try:
                             vid.video.save(output_path)
                         except:
                             pass
                     
                     if os.path.exists(output_path):
                         print(f"💾 Saved to {output_path}")
                     else:
                         print("⚠️ Failed to save video bytes")
                 else:
                    print("⚠️ Application responded but no video content.")

        except Exception as e:
            import traceback
            print(f"❌ Generation failed with {model_name}: {e}")
            traceback.print_exc()
            
    except Exception as e:
        print(f"❌ Failed to init client: {e}")

if __name__ == "__main__":
    asyncio.run(main())
