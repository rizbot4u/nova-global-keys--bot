import os
import sys
from google import genai
from google.genai import types

def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        print("Error: GEMINI_API_KEY is not set.")
        print("Set it using: export GEMINI_API_KEY='your_api_key_here'")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    print("==========================================")
    print("  Connected to Gemini (gemini-2.5-flash) ")
    print("  Google Search Grounding: ENABLED")
    print("  Type 'exit' or 'quit' to close the chat.")
    print("==========================================\n")

    # Configure the chat session with Google Search enabled
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    )
    
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=config
    )

    while True:
        try:
            user_input = input("You: ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quit"]:
                print("\nClosing chat session. Goodbye!")
                break
            
            response = chat.send_message(user_input)
            
            # Extract clean text to prevent non-text part warnings
            output_text = ""
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        output_text += part.text
            else:
                output_text = response.text or ""

            print(f"\nGemini: {output_text.strip()}\n")
            
        except KeyboardInterrupt:
            print("\nSession interrupted. Exiting...")
            break
        except Exception as e:
            print(f"\nError processing request: {e}\n")

if __name__ == "__main__":
    main()
