"""채점 결과를 선생님용 리포트(.md)와 반 전체 점수표(scores.csv)로 만든다."""
from programs.portfolio.score import PAUSE_SEC, WEIGHTS


def report_md(name, ref, result):
    s = result["score"]
    lines = [f"# {name}", ""]
    if s is None:
        lines += ["## 점수: **채점 불가** (목소리가 거의 들리지 않음 → 녹음 확인 필요)", ""]
    else:
        pt = s["points"]
        lines += [
            f"## 점수: **{s['total']:.0f}점 ({s['grade']})**", "",
            "| 항목 | 점수 | 근거 |", "|---|---|---|",
            f"| 정확도 | {pt['accuracy']:.0f}/{WEIGHTS['accuracy']} | 대본 단어 {s['accuracy'] * 100:.0f}% 맞게 읽음"
            f" (이름 {s['n_names']}개는 제외) |",
            f"| 유창성 | {pt['fluency']:.0f}/{WEIGHTS['fluency']} | 문장 안 속도 분당 {s['wpm']:.0f}단어,"
            f" {PAUSE_SEC}초 이상 멈춤 {s['pauses']}번 |",
            f"| 명확도 | {pt['clarity']:.0f}/{WEIGHTS['clarity']} | 맞게 읽은 단어의 평균 인식 확신도"
            f" {s['confidence']:.2f} |", ""]
    lines += [f"대본 일치율: **{result['rate']:.0f}%** ({result['matched']}/{len(ref)} 단어)", "",
              "| 시간 | 유형 | 대본 | 아이가 읽은 것(받아쓰기) | 판정 | 점수 차 |",
              "|---|---|---|---|---|---|"]
    for r in result["rows"]:
        gap = f"{r['check']['gap']:+.2f}" if r["check"] else "-"
        lines.append(f"| {r['t']:.1f}s | {r['kind']} | {r['script'] or '-'} | {r['said'] or '-'} "
                     f"| {r['verdict']} | {gap} |")
    lines += ["", "## 받아쓰기 전문", "", " ".join(w["text"] for w in result["hyp"]), ""]
    return "\n".join(lines)


def write_summary(summary, out_dir):
    """summary: (name, rate, todo, score) per recording. Prints a ranking and writes scores.csv."""
    # One table for the whole class; utf-8-sig so Excel shows Korean correctly.
    csv_rows = ["이름,점수,등급,정확도,유창성,명확도,일치율(%),분당 단어,멈춤,확인 필요"]
    print("\n=== 요약 ===")
    for name, rate, todo, s in sorted(summary, key=lambda x: -(x[3]["total"] if x[3] else -1)):
        if s is None:
            print(f"{name}: 채점 불가 (녹음 확인)")
            csv_rows.append(f'"{name}",,채점 불가,,,,{rate:.0f},,,{todo}')
            continue
        pt = s["points"]
        print(f"{name}: {s['total']:.0f}점 {s['grade']}  (정확도 {pt['accuracy']:.0f} / 유창성 "
              f"{pt['fluency']:.0f} / 명확도 {pt['clarity']:.0f})  분당 {s['wpm']:.0f}단어, "
              f"멈춤 {s['pauses']}, 확신도 {s['confidence']:.2f}")
        csv_rows.append(f'"{name}",{s["total"]:.0f},{s["grade"]},{pt["accuracy"]:.1f},{pt["fluency"]:.1f},'
                        f'{pt["clarity"]:.1f},{rate:.0f},{s["wpm"]:.0f},{s["pauses"]},{todo}')
    (out_dir / "scores.csv").write_text("\n".join(csv_rows) + "\n", encoding="utf-8-sig")
    print(f"-> {out_dir / 'scores.csv'}")
