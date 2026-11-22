from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config.defaults import get_transit_minutes


@dataclass(frozen=True)
class RsoSummary:
    subject_id: int
    subject_name: str
    rso_model: str
    earned_semester: float
    earned_exam: float
    total_earned: float
    max_possible_remaining: float
    projected_max: float
    admission_threshold: float
    pass_threshold: float
    points_needed_for_admission: float
    points_needed_for_pass: float
    is_admitted: bool
    is_passed: bool
    risk_level: str  # 'safe', 'warning', 'critical'


class RsoCalculator:
    """Розрахунок поточного рейтингу РСО КАІ (моделі '100_accum' та '60_40') та прогнозів."""

    @staticmethod
    def calculate_subject_rso(
        subject: Dict[str, Any], components: List[Dict[str, Any]]
    ) -> RsoSummary:
        model = subject.get("rso_model", "100_accum")
        admission_threshold = float(subject.get("admission_threshold", 36.0))
        pass_threshold = float(subject.get("pass_threshold", 60.0))

        earned_sem = 0.0
        earned_exam = 0.0
        remaining_potential = 0.0

        for comp in components:
            comp_type = comp.get("component_type", "lab")
            max_score = float(comp.get("max_score", 0.0))
            earned = comp.get("earned_score")

            if earned is not None:
                val = float(earned)
                if comp_type == "exam":
                    earned_exam += val
                else:
                    earned_sem += val
            else:
                remaining_potential += max_score

        if model == "60_40":
            earned_sem = min(earned_sem, 60.0)
            earned_exam = min(earned_exam, 40.0)

        total_earned = round(earned_sem + earned_exam, 2)
        projected_max = round(total_earned + remaining_potential, 2)

        needed_admission = max(0.0, round(admission_threshold - earned_sem, 2))
        needed_pass = max(0.0, round(pass_threshold - total_earned, 2))

        is_admitted = earned_sem >= admission_threshold
        is_passed = total_earned >= pass_threshold and is_admitted

        if not is_admitted and needed_admission > 12.0:
            risk = "critical"
        elif not is_admitted or needed_pass > 15.0:
            risk = "warning"
        else:
            risk = "safe"

        return RsoSummary(
            subject_id=int(subject["id"]),
            subject_name=str(subject["name"]),
            rso_model=model,
            earned_semester=round(earned_sem, 2),
            earned_exam=round(earned_exam, 2),
            total_earned=total_earned,
            max_possible_remaining=round(remaining_potential, 2),
            projected_max=projected_max,
            admission_threshold=admission_threshold,
            pass_threshold=pass_threshold,
            points_needed_for_admission=needed_admission,
            points_needed_for_pass=needed_pass,
            is_admitted=is_admitted,
            is_passed=is_passed,
            risk_level=risk,
        )

    @staticmethod
    def simulate_what_if(
        subject: Dict[str, Any],
        components: List[Dict[str, Any]],
        hypothetical_scores: Dict[int, float],
    ) -> RsoSummary:
        """Моделює підсумковий бал при підстановці очікуваних оцінок за нездані роботи."""
        simulated: List[Dict[str, Any]] = []
        for comp in components:
            copy_comp = dict(comp)
            cid = int(comp["id"])
            if cid in hypothetical_scores:
                copy_comp["earned_score"] = min(
                    float(comp.get("max_score", 100.0)),
                    max(0.0, float(hypothetical_scores[cid])),
                )
            simulated.append(copy_comp)
        return RsoCalculator.calculate_subject_rso(subject, simulated)


class ParityResolver:
    """Визначає поточний навчальний тиждень (1-й чисельник / 2-й знаменник) від опорної дати."""

    @staticmethod
    def get_week_parity(target_date: date, anchor_date: date) -> str:
        anchor_monday = anchor_date - timedelta(days=anchor_date.weekday())
        target_monday = target_date - timedelta(days=target_date.weekday())
        weeks_diff = (target_monday - anchor_monday).days // 7
        # 0-й, 2-й, 4-й тижні від старту -> 1-й навчальний тиждень ('odd' / чисельник)
        return "odd" if (weeks_diff % 2 == 0) else "even"

    @staticmethod
    def format_parity_ua(parity: str) -> str:
        return "1-й тиждень (Чисельник)" if parity == "odd" else "2-й тиждень (Знаменник)"

    @staticmethod
    def is_entry_active_on_parity(entry_parity: str, current_parity: str) -> bool:
        p = (entry_parity or "both").lower()
        return p == "both" or p == current_parity


@dataclass(frozen=True)
class ScheduleWindow:
    start_time: str
    end_time: str
    total_gap_minutes: int
    transit_minutes: int
    net_productive_minutes: int
    from_building: str
    to_building: str
    recommendation: str


class WindowAnalyzer:
    """Знаходить вільні «вікна» між парами на день та віднімає час переходу між корпусами КАІ."""

    @staticmethod
    def _to_minutes(hhmm: str) -> int:
        parts = hhmm.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])

    @staticmethod
    def _from_minutes(total: int) -> str:
        return f"{total // 60:02d}:{total % 60:02d}"

    @classmethod
    def find_productive_windows(
        cls,
        day_classes: List[Dict[str, Any]],
        min_productive_minutes: int = 35,
    ) -> List[ScheduleWindow]:
        if len(day_classes) < 2:
            return []

        sorted_classes = sorted(day_classes, key=lambda c: cls._to_minutes(c["start_time"]))
        windows: List[ScheduleWindow] = []

        for idx in range(len(sorted_classes) - 1):
            curr_cls = sorted_classes[idx]
            next_cls = sorted_classes[idx + 1]

            end_m = cls._to_minutes(curr_cls["end_time"])
            start_next_m = cls._to_minutes(next_cls["start_time"])
            gap = start_next_m - end_m
            if gap <= 15:
                continue

            b_from = str(curr_cls.get("building", "1"))
            b_to = str(next_cls.get("building", "1"))
            transit = get_transit_minutes(b_from, b_to)
            net_minutes = max(0, gap - transit - 5)  # 5 хв буфер на підготовку

            if net_minutes >= min_productive_minutes:
                rec = (
                    "Ідеально для 1 сесії Pomodoro (45/15) або оформлення лабораторної"
                    if net_minutes >= 45
                    else "Підходить для повторення конспекту Корнелла (Фаза 24) або карток"
                )
                windows.append(
                    ScheduleWindow(
                        start_time=cls._from_minutes(end_m + 3),
                        end_time=cls._from_minutes(start_next_m - transit),
                        total_gap_minutes=gap,
                        transit_minutes=transit,
                        net_productive_minutes=net_minutes,
                        from_building=b_from,
                        to_building=b_to,
                        recommendation=rec,
                    )
                )
        return windows

    @staticmethod
    def calculate_smart_reminder_lead(
        prev_class: Optional[Dict[str, Any]],
        target_class: Dict[str, Any],
        default_lead: int = 15,
    ) -> Tuple[int, str]:
        """Повертає час нагадування до пари (30 хв, якщо перехід між різними корпусами КАІ)."""
        if not prev_class:
            return default_lead, f"Нагадування за {default_lead} хв (корпус {target_class.get('building', '1')})"

        b_prev = str(prev_class.get("building", "")).strip().upper()
        b_next = str(target_class.get("building", "")).strip().upper()
        if b_prev and b_next and b_prev != b_next:
            transit = get_transit_minutes(b_prev, b_next)
            lead = max(25, transit + 15)
            return lead, f"Перехід корпус {b_prev} → корпус {b_next} (~{transit} хв), нагадати за {lead} хв"
        return default_lead, f"Той самий корпус ({b_next or '1'}), нагадати за {default_lead} хв"