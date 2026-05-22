import google.genai as genai
from app.core.config import settings

# Configure Gemini once
genai.configure(api_key=settings.GEMINI_API_KEY)

# Shared model instance
gemini_model = genai.GenerativeModel("gemini-1.5-pro")

# Generate content
response = gemini_model.generate_content("Write a short greeting")
print(response.text)