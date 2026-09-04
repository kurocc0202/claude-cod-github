"""Fixture data below is invented for tests only. None of it is a real project."""

import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lead_grading  # noqa: E402
import scoring  # noqa: E402

TODAY = dt.date(2026, 9, 4)


def signal(**kw):
    base = {
        "project_id": "P1",
        "signal_type": "複驗",
        "source_name": "來源A",
        "source_url": "https://example.com/post/1",
        "post_date": "2026-09-01",
        "event_date": "2026-08-30",
        "checked_at": "2026-09-03",
        "confidence": "high",
        "is_leftover_unit": "",
        "is_show_unit": "",
    }
    base.update(kw)
    return base


class DedupeTests(unittest.TestCase):
    def test_same_url_counts_once(self):
        a = signal(source_url="https://www.example.com/post/1/")
        b = signal(source_url="http://example.com/post/1?utm=x")
        self.assertEqual(len(scoring.dedupe_signals([a, b])), 1)

    def test_same_event_from_different_posts_counts_once(self):
        a = signal(source_url="https://example.com/1")
        b = signal(source_url="https://example.com/2")
        self.assertEqual(len(scoring.dedupe_signals([a, b])), 1)

    def test_different_events_kept(self):
        a = signal(source_url="https://example.com/1", signal_type="初驗")
        b = signal(source_url="https://example.com/2", signal_type="複驗")
        self.assertEqual(len(scoring.dedupe_signals([a, b])), 2)


class DeliveryConfidenceTests(unittest.TestCase):
    def test_no_signals_is_zero_and_marked_unknown(self):
        score, breakdown = scoring.delivery_confidence("P1", [], TODAY)
        self.assertEqual(score, 0)
        self.assertEqual(breakdown[0]["basis"], "未查得")

    def test_event_date_beats_post_date_for_recency(self):
        # posted today about an event 40 days ago -> recency uses the event
        sig = signal(post_date="2026-09-04", event_date="2026-07-26")
        _, breakdown = scoring.delivery_confidence("P1", [sig], TODAY)
        recency = next(b for b in breakdown if b["item"] == "最新訊號距今")
        self.assertEqual(recency["points"], 8)
        self.assertIn("40 天", recency["basis"])

    def test_fresh_strong_multi_source_scores_high(self):
        sigs = [
            signal(source_url="https://example.com/1", signal_type="複驗", source_name="A"),
            signal(source_url="https://example.com/2", signal_type="交屋", source_name="B",
                   event_date="2026-09-02"),
            signal(source_url="https://example.com/3", signal_type="搬家", source_name="C",
                   event_date="2026-09-03"),
        ]
        score, breakdown = scoring.delivery_confidence("P1", scoring.dedupe_signals(sigs), TODAY)
        # recency 30 + strongest 30 + 3 distinct types 12 + 3 sources 10
        self.assertEqual(score, 82)
        self.assertTrue(all("basis" in b for b in breakdown))

    def test_low_confidence_signal_is_discounted(self):
        sig = signal(signal_type="交屋", confidence="low")
        _, breakdown = scoring.delivery_confidence("P1", [sig], TODAY)
        strongest = next(b for b in breakdown if b["item"] == "最強訊號種類")
        self.assertEqual(strongest["points"], 12)

    def test_leftover_and_show_unit_penalised(self):
        sig = signal(is_leftover_unit="是", is_show_unit="是")
        score, _ = scoring.delivery_confidence("P1", [sig], TODAY)
        clean, _ = scoring.delivery_confidence("P1", [signal()], TODAY)
        self.assertEqual(clean - score, 25)

    def test_score_never_negative(self):
        sig = signal(signal_type="未知", event_date="2025-01-01", is_leftover_unit="是")
        score, _ = scoring.delivery_confidence("P1", [sig], TODAY)
        self.assertEqual(score, 0)


class FitTests(unittest.TestCase):
    def test_missing_fields_are_unknown_not_guessed(self):
        score, breakdown = scoring.fit_score({"project_id": "P1"})
        self.assertEqual(score, 0)
        self.assertTrue(all(b["basis"] == "未查得" for b in breakdown))

    def test_typical_first_home_project(self):
        project = {
            "main_layout": "3房",
            "indoor_ping_min": "24",
            "indoor_ping_max": "32",
            "developer_finish_level": "none",
            "buyer_profile": "首購小家庭",
            "needs": "玄關|電器櫃|電視櫃|衣櫃|其他",
        }
        score, _ = scoring.fit_score(project)
        self.assertEqual(score, 30 + 20 + 15 + 15 + 20)

    def test_fully_finished_units_lose_points(self):
        base = {"main_layout": "3房", "developer_finish_level": "none"}
        full = dict(base, developer_finish_level="full")
        self.assertEqual(scoring.fit_score(base)[0] - scoring.fit_score(full)[0], 35)


class RecheckTests(unittest.TestCase):
    def test_stale_check_flags_recheck(self):
        self.assertTrue(scoring.recheck_due("P1", [signal(checked_at="2026-08-01")], TODAY))
        self.assertFalse(scoring.recheck_due("P1", [signal(checked_at="2026-09-01")], TODAY))
        self.assertTrue(scoring.recheck_due("P1", [signal(checked_at="")], TODAY))


class ScoreAllTests(unittest.TestCase):
    def test_sorted_by_cluster_then_confidence(self):
        projects = [
            {"project_id": "P2", "project_name": "乙", "cluster": "楠梓"},
            {"project_id": "P1", "project_name": "甲", "cluster": "楠梓"},
            {"project_id": "P3", "project_name": "丙", "cluster": ""},
        ]
        sigs = [signal(project_id="P1")]
        rows = scoring.score_all(projects, sigs, TODAY)
        self.assertEqual([r["project_id"] for r in rows], ["P3", "P1", "P2"])
        self.assertEqual(rows[0]["cluster"], "未分組")


class LeadGradingTests(unittest.TestCase):
    def lead(self, **kw):
        base = {
            "project_name": "測試建案",
            "house_stage": "已完成交屋",
            "layout": "3房",
            "start_timing": "1至3個月",
            "priority_space": "玄關",
            "has_floor_plan": "是",
            "will_share_floor_plan": "是",
            "consent": "是",
        }
        base.update(kw)
        return base

    def test_a_grade(self):
        g, reasons = lead_grading.grade(self.lead())
        self.assertEqual(g, "A")
        self.assertIn("已有平面圖", reasons)

    def test_b_grade_when_timing_is_later(self):
        self.assertEqual(lead_grading.grade(self.lead(start_timing="3至6個月"))[0], "B")

    def test_b_grade_when_not_yet_delivered(self):
        self.assertEqual(lead_grading.grade(self.lead(house_stage="等待驗屋"))[0], "B")

    def test_c_grade_without_consent(self):
        self.assertEqual(lead_grading.grade(self.lead(consent="否"))[0], "C")

    def test_c_grade_without_project_or_stage(self):
        self.assertEqual(lead_grading.grade(self.lead(project_name="", house_stage=""))[0], "C")

    def test_b_grade_when_timing_undecided_but_need_is_clear(self):
        lead = self.lead(start_timing="尚未確定", has_floor_plan="否", will_share_floor_plan="否")
        self.assertEqual(lead_grading.grade(lead)[0], "B")

    def test_c_grade_without_timing_plan_or_space_need(self):
        lead = self.lead(start_timing="尚未確定", has_floor_plan="否",
                         will_share_floor_plan="否", priority_space="")
        self.assertEqual(lead_grading.grade(lead)[0], "C")


if __name__ == "__main__":
    unittest.main()
