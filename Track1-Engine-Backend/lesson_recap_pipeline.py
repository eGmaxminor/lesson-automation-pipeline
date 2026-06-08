"""
lesson_recap_pipeline.py
------------------------
Automation pipeline that converts transcribed teacher voice notes into
structured, student-personalized lesson recaps — now with an active
SQLAlchemy/SQLite persistence layer.

Architecture:
  Part 1 - Data Schema   : dataclasses (DTOs) + active SQLAlchemy ORM models
  Part 2 - Logic Engine  : RecapPromptBuilder + LLM client wrapper
  Part 3 - Infrastructure: env-var secrets, resilient API calls,
                           SQLite persistence via SQLAlchemy

Author: Music Studio Automation Project
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    create_engine,
    inspect,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# ---------------------------------------------------------------------------
# Logging configuration (enterprise-friendly default)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("lesson_recap")


# ===========================================================================
# PART 1: DATA SCHEMA
# ===========================================================================
# Lightweight dataclasses act as in-memory DTOs used by the logic engine.
# The SQLAlchemy ORM mirrors below provide persistence.
# ---------------------------------------------------------------------------

@dataclass
class Teacher:
    """Represents an instructor in the studio."""
    id: int
    name: str
    email: str


@dataclass
class Student:
    """Represents a student receiving lessons."""
    id: int
    name: str
    age: int
    gender: str
    email: str


@dataclass
class LessonSession:
    """A single scheduled lesson between a teacher and student."""
    id: int
    student_id: int
    teacher_id: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LessonNotes:
    """Raw + structured notes attached to a LessonSession."""
    id: int
    session_id: int
    raw_transcript: str
    structured_recap: Optional[str] = None


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models (active persistence layer)
# ---------------------------------------------------------------------------
Base = declarative_base()


class TeacherORM(Base):
    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    sessions = relationship("LessonSessionORM", back_populates="teacher")


class StudentORM(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    gender = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    sessions = relationship("LessonSessionORM", back_populates="student")


class LessonSessionORM(Base):
    __tablename__ = "lesson_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    student = relationship("StudentORM", back_populates="sessions")
    teacher = relationship("TeacherORM", back_populates="sessions")
    notes = relationship(
        "LessonNotesORM",
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )


class LessonNotesORM(Base):
    __tablename__ = "lesson_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("lesson_sessions.id"), nullable=False)
    raw_transcript = Column(Text, nullable=False)
    structured_recap = Column(Text, nullable=True)

    session = relationship("LessonSessionORM", back_populates="notes")


# ---------------------------------------------------------------------------
# Database bootstrap helpers
# ---------------------------------------------------------------------------
_SessionFactory: Optional[sessionmaker] = None
_ENGINE = None


def init_db(db_path: str = "studio.db"):
    """
    Initialize a local SQLite database at `db_path`.

    - Creates the file if it doesn't exist.
    - Creates any missing tables.
    - Caches a module-level session factory for reuse.

    Returns the SQLAlchemy engine.
    """
    global _SessionFactory, _ENGINE

    db_existed = os.path.exists(db_path)
    db_url = f"sqlite:///{db_path}"

    logger.info(
        "Initializing database at '%s' (existing=%s).", db_path, db_existed
    )

    try:
        engine = create_engine(db_url, echo=False, future=True)
        Base.metadata.create_all(engine)

        # Inspect to confirm tables exist (useful for portfolio-grade logs)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        logger.info("Tables available: %s", ", ".join(tables) or "<none>")

        _ENGINE = engine
        _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return engine

    except Exception as e:
        logger.exception("Failed to initialize database: %s", e)
        raise


def _get_session() -> Session:
    """Return a new SQLAlchemy session; auto-initializes the DB if needed."""
    if _SessionFactory is None:
        logger.warning("Session factory not initialized; calling init_db() with defaults.")
        init_db()
    return _SessionFactory()  # type: ignore[misc]

def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = _get_session()
    try:
        yield db
    finally:
        db.close()

# ===========================================================================
# PART 2: LOGIC ENGINE
# ===========================================================================

class RecapPromptBuilder:
    """
    Builds a deterministic, business-rule-governed LLM prompt for a given
    Student + raw transcript pair.
    """

    WORD_REPLACEMENTS = {
        r"\btoday\b":     "last class",
        r"\bhi\b":        "hey",
        r"\bour class\b": "your class",
    }

    SIGN_OFF = "Till next time, take care!"
    SIGNATURE = "Mr. E"
    YOUNG_LEARNER_AGE = 10

    def __init__(self, student: Student, raw_transcript: str):
        self.student = student
        self.raw_transcript = raw_transcript

    def _apply_word_replacements(self, text: str) -> str:
        for pattern, replacement in self.WORD_REPLACEMENTS.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _learned_emoji(self) -> str:
        return "🌟" if self.student.age < self.YOUNG_LEARNER_AGE else "✨"

    def _tone_instruction(self) -> str:
        if self.student.age < self.YOUNG_LEARNER_AGE:
            return (
                "Write in a warm, playful, encouraging tone suitable for a "
                f"young child (~{self.student.age} years old). Use simple "
                "vocabulary, short sentences, and gentle excitement."
            )
        return (
            "Write in a clear, motivating, age-appropriate tone for a "
            f"{self.student.age}-year-old student. Be encouraging but mature."
        )

    def build_prompt(self) -> str:
        cleaned_transcript = self._apply_word_replacements(self.raw_transcript)
        learned_emoji = self._learned_emoji()

        prompt = f"""
You are an assistant that transforms a music teacher's raw voice-note
transcript into a structured lesson recap email for a student.

STUDENT PROFILE
  - Name:   {self.student.name}
  - Age:    {self.student.age}
  - Gender: {self.student.gender}

TONE
  {self._tone_instruction()}

STRICT FORMATTING RULES
  1. Produce exactly three sections, in this order, using these headers:
       {learned_emoji} What we Learned
       🎹 Your Practice Goals/What to Focus on
       🎶 What's coming up Next!
  2. Replace any occurrence of:
       - "today"     -> "last class"
       - "hi"        -> "hey"
       - "our class" -> "your class"
     (already pre-processed, but reinforce on any new text you generate).
  3. The message MUST end with the line:
       {self.SIGN_OFF}
     followed by EXACTLY three blank lines, then the signature:
       {self.SIGNATURE}
  4. Do NOT add any content after the signature.
  5. Address the student by first name at the opening.

RAW TRANSCRIPT (pre-processed)
\"\"\"
{cleaned_transcript.strip()}
\"\"\"

Now produce the final recap.
""".strip()

        return prompt


# ===========================================================================
# PART 3: PROFESSIONAL INFRASTRUCTURE - LLM CLIENT
# ===========================================================================

class LLMRecapClient:
    """Resilient LLM wrapper with env-var secret management."""

    def __init__(self, provider: str = "openai"):
        self.provider = provider.lower()

        if self.provider == "openai":
            self.api_key = os.environ.get("OPENAI_API_KEY")
            self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        elif self.provider == "anthropic":
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
            self.model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        if not self.api_key:
            raise EnvironmentError(
                f"Missing API key for provider '{self.provider}'. "
                "Set the appropriate environment variable."
            )

    def generate_recap(self, prompt: str, max_tokens: int = 800) -> str:
        try:
            if self.provider == "openai":
                return self._call_openai(prompt, max_tokens)
            return self._call_anthropic(prompt, max_tokens)

        except ImportError as e:
            logger.error("Provider SDK not installed: %s", e)
            raise
        except TimeoutError as e:
            logger.error("LLM request timed out: %s", e)
            raise
        except ConnectionError as e:
            logger.error("Network error reaching LLM provider: %s", e)
            raise
        except Exception as e:
            logger.exception("Unexpected error during LLM call: %s", e)
            raise

    def _call_openai(self, prompt: str, max_tokens: int) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a precise lesson-recap formatter."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.4,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def _call_anthropic(self, prompt: str, max_tokens: int) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)

        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


# ===========================================================================
# PERSISTENCE HELPERS
# ===========================================================================

def _upsert_student(session: Session, student: Student) -> StudentORM:
    """Insert or update a student row keyed on the DTO id (or email fallback)."""
    row = session.get(StudentORM, student.id)
    if row is None:
        row = StudentORM(
            id=student.id,
            name=student.name,
            age=student.age,
            gender=student.gender,
            email=student.email,
        )
        session.add(row)
        logger.info("Inserted new student id=%s (%s).", student.id, student.name)
    else:
        row.name = student.name
        row.age = student.age
        row.gender = student.gender
        row.email = student.email
        logger.info("Updated existing student id=%s.", student.id)
    return row


def _upsert_teacher(session: Session, teacher: Teacher) -> TeacherORM:
    row = session.get(TeacherORM, teacher.id)
    if row is None:
        row = TeacherORM(id=teacher.id, name=teacher.name, email=teacher.email)
        session.add(row)
        logger.info("Inserted new teacher id=%s (%s).", teacher.id, teacher.name)
    return row


def _persist_session_and_notes(
    student: Student,
    teacher: Teacher,
    raw_transcript: str,
    structured_recap: str,
) -> int:
    """
    Persist the LessonSession + LessonNotes records.
    Returns the newly created session_id.
    """
    db = _get_session()
    try:
        _upsert_student(db, student)
        _upsert_teacher(db, teacher)

        session_row = LessonSessionORM(
            student_id=student.id,
            teacher_id=teacher.id,
            timestamp=datetime.utcnow(),
        )
        db.add(session_row)
        db.flush()  # populate session_row.id

        notes_row = LessonNotesORM(
            session_id=session_row.id,
            raw_transcript=raw_transcript,
            structured_recap=structured_recap,
        )
        db.add(notes_row)

        db.commit()
        logger.info(
            "Persisted lesson session id=%s with notes id=%s.",
            session_row.id, notes_row.id,
        )
        return session_row.id

    except Exception as e:
        db.rollback()
        logger.exception("Database write failed; rolled back transaction: %s", e)
        raise
    finally:
        db.close()


# ===========================================================================
# ORCHESTRATION
# ===========================================================================

def generate_structured_recap(
    student: Student,
    raw_transcript: str,
    teacher: Optional[Teacher] = None,
    provider: str = "openai",
    db_path: str = "studio.db",
    persist: bool = True,
) -> str:
    """
    High-level entrypoint:
      Student + raw transcript  ->  LLM-generated recap  ->  persisted to SQLite.

    Args:
        student:        Student DTO.
        raw_transcript: Raw teacher voice-note transcript.
        teacher:        Optional Teacher DTO (defaults to Mr. E placeholder).
        provider:       'openai' or 'anthropic'.
        db_path:        Path to the local SQLite DB.
        persist:        If False, skips DB writes (useful for dry-runs).

    Returns:
        The structured recap string from the LLM.
    """
    # Ensure DB is initialized before any work (cheap if already done)
    if persist:
        init_db(db_path=db_path)

    # Default teacher placeholder so persistence always has a FK target
    if teacher is None:
        teacher = Teacher(id=1, name="Mr. E", email="mr.e@studio.local")

    # 1) Build prompt
    builder = RecapPromptBuilder(student=student, raw_transcript=raw_transcript)
    prompt = builder.build_prompt()
    logger.info("Prompt built for student id=%s (age=%s).", student.id, student.age)

    # 2) Call LLM
    client = LLMRecapClient(provider=provider)
    recap = client.generate_recap(prompt)
    logger.info("Recap successfully generated (%d chars).", len(recap))

    # 3) Persist on success
    if persist:
        try:
            session_id = _persist_session_and_notes(
                student=student,
                teacher=teacher,
                raw_transcript=raw_transcript,
                structured_recap=recap,
            )
            logger.info("Recap saved under lesson_session id=%s.", session_id)
        except Exception as e:
            # We still return the recap text so the caller isn't blocked,
            # but the failure is loudly logged for ops visibility.
            logger.error("Recap generated but NOT persisted: %s", e)

    return recap


# ===========================================================================
# DEMO / SMOKE TEST
# ===========================================================================
if __name__ == "__main__":
    # Initialize DB explicitly for visibility
    init_db("studio.db")

    demo_teacher = Teacher(
        id=1,
        name="Mr. E",
        email="mr.e@studio.local",
    )

    demo_student = Student(
        id=1,
        name="Lily",
        age=8,
        gender="female",
        email="lily@example.com",
    )

    demo_transcript = (
        "Hi Lily! Today in our class we worked on the C major scale, "
        "and you did a great job with both hands together. "
        "For next time, focus on slow practice with a metronome at 60 BPM. "
        "Next week we'll start a new song called 'Ocean Waves'."
    )

    try:
        recap_output = generate_structured_recap(
            student=demo_student,
            raw_transcript=demo_transcript,
            teacher=demo_teacher,
        )
        print("\n--- STRUCTURED RECAP ---\n")
        print(recap_output)
    except Exception as err:
        logger.error("Pipeline failed: %s", err)
