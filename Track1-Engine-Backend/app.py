import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# This points directly to your exact function and Student DTO data structure
from lesson_recap_pipeline import generate_structured_recap, Student 

app = FastAPI(title="Ageless Tune Studio Pipeline Bridge")

# Security Gateway for Lovable cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LessonRequest(BaseModel):
    student_name: str
    raw_notes: str

@app.post("/api/recap")
async def process_lesson_recap(payload: LessonRequest):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="Missing OpenAI API Key on your local system environment.")
    
    try:
        # 1. Create a Student DTO placeholder matching your pipeline requirements.
        # (For the MVP, we pass the incoming name from the dashboard dynamically)
        active_student = Student(
            id=99, 
            name=payload.student_name, 
            age=12,  # Mature profile default; can be wired dynamically next
            gender="unknown", 
            email="client@agelesstune.local"
        )
        
        # 2. Call your actual orchestration entrypoint function
        formatted_recap = generate_structured_recap(
            student=active_student, 
            raw_transcript=payload.raw_notes,
            persist=True  # Automatically triggers your SQLAlchemy SQLite engine
        )
        
        return {
            "status": "success",
            "student_name": payload.student_name,
            "recap_data": formatted_recap
        }
        
    except Exception as e:
       import traceback
       traceback.print_exc()  # <--- This will force-print the actual error to your terminal
       raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)