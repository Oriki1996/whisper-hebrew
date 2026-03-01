# whisper-hebrew 🎙️

תמלול הרצאות אקדמיות בעברית עם OpenAI Whisper + תיקון אוטומטי דרך Claude.

## התקנה

```bash
pip install -r requirements.txt
cp .env.example .env
# ערוך .env והוסף את מפתח ה-Anthropic שלך (אופציונלי)
```

## שימוש

### CLI

```bash
# קובץ בודד
python transcribe.py "lecture.mp4"

# עם מודל medium ותיקון Claude
python transcribe.py "lecture.mp4" --model medium --fix

# תיקייה שלמה (batch)
python transcribe.py "C:\Downloads\Video" --model small

# אפשרויות נוספות
python transcribe.py --help
```

### Web UI

```bash
python server.py
# → http://localhost:5000
```

## מודלים

| מודל | גודל | מהירות | דיוק |
|------|------|--------|------|
| tiny | 39MB | ⚡⚡⚡ | בסיסי |
| small | 244MB | ⚡⚡ | טוב |
| medium | 769MB | ⚡ | גבוה |
| large | 1.5GB | 🐢 | מקסימלי |

> מומלץ: `small` ל-CPU, `medium` עם GPU

## ffmpeg

ffmpeg נדרש לפענוח אודיו. ניתן להתקין:

```powershell
winget install --id Gyan.FFmpeg
```

הפרויקט מזהה אוטומטית את ffmpeg גם לאחר התקנה דרך winget.

## תיקון עברית עם Claude

הפעל `--fix` ב-CLI או סמן "תיקון עם Claude" ב-Web UI.
דורש `ANTHROPIC_API_KEY` ב-.env (או הגדרות בממשק הוב).
משתמש במודל `claude-haiku-4-5` — מהיר וזול.
