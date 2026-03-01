#!/usr/bin/env python3
"""
transcribe.py — CLI for Hebrew speech-to-text with optional Claude correction.

Usage:
  python transcribe.py <file_or_folder> [options]

Examples:
  python transcribe.py lecture.mp4
  python transcribe.py "C:\\Downloads\\Video" --model medium --fix
  python transcribe.py lecture.mp4 --model large --lang he --out ./results
"""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="תמלול הרצאות עברית עם Whisper + Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="קובץ אודיו/וידאו או תיקייה לעיבוד batch")
    parser.add_argument(
        "--model", "-m",
        default="small",
        choices=["tiny", "small", "medium", "large"],
        help="מודל Whisper (ברירת מחדל: small)",
    )
    parser.add_argument(
        "--lang", "-l",
        default="he",
        help="קוד שפה (ברירת מחדל: he לעברית)",
    )
    parser.add_argument(
        "--fix", "-f",
        action="store_true",
        help="תקן את התמלול עם Claude (דורש ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--out", "-o",
        default=None,
        help="תיקיית פלט (ברירת מחדל: ./output)",
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="עבד מחדש גם קבצים שכבר תומללו",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.out) if args.out else None

    if not input_path.exists():
        print(f"שגיאה: הנתיב לא קיים — {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.is_dir():
        _run_batch(input_path, args, output_dir)
    else:
        _run_single(input_path, args, output_dir)


def _run_single(file_path: Path, args, output_dir):
    from core.whisper_runner import transcribe
    from core.claude_fixer import fix_hebrew

    try:
        from tqdm import tqdm
        pbar = tqdm(total=100, desc=file_path.name, unit="%", ncols=80)

        def progress(pct, msg):
            pbar.n = int(pct * 100)
            pbar.set_postfix_str(msg[:50])
            pbar.refresh()

        result = transcribe(
            file_path=file_path,
            model_name=args.model,
            language=args.lang,
            output_dir=output_dir,
            progress_cb=progress,
        )
        pbar.n = 95
        pbar.refresh()

        if args.fix:
            pbar.set_description("תיקון Claude")
            try:
                fixed = fix_hebrew(result["text"])
                result["fixed_text"] = fixed
                Path(result["txt_path"]).write_text(fixed, encoding="utf-8")
                pbar.set_postfix_str("תוקן בהצלחה")
            except Exception as e:
                pbar.set_postfix_str(f"שגיאת Claude: {e}")

        pbar.n = 100
        pbar.close()

        print(f"\nהושלם!")
        print(f"  TXT: {result['txt_path']}")
        print(f"  SRT: {result['srt_path']}")
        print(f"\nתצוגה מקדימה (100 תווים ראשונים):")
        text = result.get("fixed_text") or result["text"]
        print(f"  {text[:200].strip()}")

    except Exception as e:
        print(f"\nשגיאה: {e}", file=sys.stderr)
        sys.exit(1)


def _run_batch(folder: Path, args, output_dir):
    from core.batch import find_audio_files, process_folder
    from tqdm import tqdm

    files = find_audio_files(folder)
    if not files:
        print(f"לא נמצאו קבצי אודיו/וידאו בתיקייה: {folder}")
        return

    print(f"נמצאו {len(files)} קבצים לעיבוד:")
    for f in files:
        print(f"  - {f.name}")
    print()

    pbar = tqdm(total=len(files), desc="batch", unit="קובץ", ncols=80)

    def progress(file_idx, total, file_name, pct, msg):
        pbar.set_description(f"[{file_idx}/{total}] {file_name[:30]}")
        pbar.set_postfix_str(msg[:40])
        if pct >= 1.0:
            pbar.update(1)

    results = process_folder(
        folder=folder,
        model=args.model,
        language=args.lang,
        fix=args.fix,
        output_dir=output_dir,
        skip_existing=not args.no_skip,
        progress_cb=progress,
    )
    pbar.close()

    done = [r for r in results if not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]

    print(f"\nסיכום:")
    print(f"  עובדו: {len(done)} קבצים")
    if skipped:
        print(f"  דולגו (כבר קיימים): {len(skipped)} קבצים")
    for r in done:
        print(f"  ✓ {Path(r['txt_path']).name}")


if __name__ == "__main__":
    main()
