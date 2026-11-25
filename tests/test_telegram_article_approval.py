"""Telegram approval of BOSS KG draft articles (Bryce, 2026-11-21): Approve / Reject buttons, replies
matched to their card, no double answers. Fake Telegram only: nothing is sent, published or pushed.

    python -m unittest tests.test_telegram_article_approval -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import notify                      # noqa: E402
from tools import article_tg as atg          # noqa: E402
from tools import publish_article as pa      # noqa: E402
from tools import telegram_poller as poller  # noqa: E402

CHAT = "4242"
P1 = "gta-6-heist-mode-leaks"                # pending, has a card (message 111)
P2 = "marvel-rivals-season-9-dates"          # pending, older notice only (no card id)
LIVE = "gta-6-players-are-already-pulling-off-spectacular-stunts-in-launch-wee"
REJ = "old-rumour-story"

TITLES = {P1: "GTA 6 Heist Mode Leaks Ahead of Update",
          P2: "Marvel Rivals Season 9 Dates Confirmed",
          LIVE: "GTA 6 Players Are Already Pulling Off Spectacular Stunts in Launch Week",
          REJ: "Old Rumour Story"}


def _md(title, extra):
    return ("---\n" f'title: "{title}"\n' 'excerpt: "Short summary."\n' 'category: "Gaming"\n'
            "date: 2026-11-20\n" 'author: "BOSS KG"\n' + extra + 'sourceName: "IGN"\n---\n\nBody.\n')


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self.next_id = 900

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        if method == "sendMessage":
            self.next_id += 1
            return {"message_id": self.next_id}
        return True

    def of(self, method):
        return [p for m, p in self.calls if m == method]

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m in ("sendMessage", "editMessageText")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / f"{P1}.md").write_text(_md(TITLES[P1], "draft: true\ntelegramMessageId: 111\n"), encoding="utf-8")
        (d / f"{P2}.md").write_text(_md(TITLES[P2], "draft: true\n"), encoding="utf-8")
        (d / f"{LIVE}.md").write_text(_md(TITLES[LIVE], "draft: false\n"), encoding="utf-8")
        (d / f"{REJ}.md").write_text(_md(TITLES[REJ], "draft: true\nrejected: true\n"), encoding="utf-8")
        self.dir = d
        self.out = d / "gh_output.txt"
        self.out.write_text("", encoding="utf-8")
        self.tg = FakeTelegram()
        self.patches = [
            mock.patch.object(atg, "ART_DIR", d),
            mock.patch.object(pa, "ART_DIR", d),
            mock.patch.object(notify, "_creds", lambda: ("TOKEN", CHAT)),
            mock.patch.object(notify, "_call", self.tg),
            mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.out), "TELEGRAM_CHAT_ID": CHAT,
                                         "TELEGRAM_BOT_TOKEN": "TOKEN"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    # -- helpers
    def poll(self, updates):
        def fake_tg(method, **params):
            return {} if params.get("offset") else {"result": updates}
        with mock.patch.object(poller, "_tg", fake_tg), mock.patch.object(sys, "argv", ["x", "--check"]):
            poller.main()
        out = {}
        for ln in self.out.read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            out[k] = v
        return out

    @staticmethod
    def tap(uid, data, mid=111, text="📝 New BOSS KG draft article\n• x", markup=None):
        msg = {"message_id": mid, "chat": {"id": int(CHAT)}, "text": text,
               "reply_markup": markup or {"inline_keyboard": []}}
        return {"update_id": uid, "callback_query": {"id": f"cq{uid}", "data": data, "message": msg}}

    @staticmethod
    def reply(uid, text, reply_to):
        return {"update_id": uid, "message": {"message_id": 5000 + uid, "chat": {"id": int(CHAT)},
                                              "text": text, "reply_to_message": reply_to}}

    @staticmethod
    def text(uid, text):
        return {"update_id": uid, "message": {"message_id": 5000 + uid, "chat": {"id": int(CHAT)},
                                              "text": text}}

    def assertNoWhichList(self):
        for t in self.tg.texts():
            self.assertNotIn("Which article", t)
            self.assertNotIn("couldn't tell which", t)


class ButtonTests(Base):
    def test_approve_button_publishes_that_article_and_locks_the_card(self):
        sid = atg.short_id(P1)
        out = self.poll([self.tap(1, f"art:a:{sid}", markup=atg.buttons(P1))])
        self.assertEqual(out["articles"], f"a:{P1}")
        self.assertEqual(out["fire"], "0")
        self.assertEqual(len(self.tg.of("answerCallbackQuery")), 1)
        edits = self.tg.of("editMessageText")
        self.assertEqual(edits[0]["message_id"], 111)
        self.assertIn("Approved", edits[0]["text"])
        self.assertNotIn("reply_markup", edits[0])            # buttons removed: no second tap
        self.assertNoWhichList()

    def test_reject_button(self):
        out = self.poll([self.tap(1, f"art:r:{atg.short_id(P1)}", markup=atg.buttons(P1))])
        self.assertEqual(out["articles"], f"r:{P1}")
        self.assertIn("Rejected", self.tg.of("editMessageText")[0]["text"])

    def test_double_tap_same_batch_is_one_decision(self):
        sid = atg.short_id(P1)
        out = self.poll([self.tap(1, f"art:a:{sid}"), self.tap(2, f"art:a:{sid}")])
        self.assertEqual(out["articles"], f"a:{P1}")

    def test_change_of_mind_in_same_batch_last_wins(self):
        sid = atg.short_id(P1)
        out = self.poll([self.tap(1, f"art:a:{sid}"), self.tap(2, f"art:r:{sid}")])
        self.assertEqual(out["articles"], f"r:{P1}")

    def test_double_tap_after_publish_says_already_live_once(self):
        out = self.poll([self.tap(1, f"art:a:{atg.short_id(LIVE)}", mid=222, markup=atg.buttons(LIVE))])
        self.assertEqual(out["articles"], "")
        self.assertEqual(out["fire"], "0")
        self.assertIn("Already live", self.tg.of("answerCallbackQuery")[0]["text"])
        self.assertEqual(len(self.tg.of("sendMessage")), 0)    # the card edit is the only message
        self.assertNoWhichList()

    def test_tap_on_rejected_draft(self):
        out = self.poll([self.tap(1, f"art:a:{atg.short_id(REJ)}", markup=atg.buttons(REJ))])
        self.assertEqual(out["articles"], "")
        self.assertIn("Already rejected", self.tg.of("answerCallbackQuery")[0]["text"])

    def test_picker_tap_removes_only_that_row(self):
        items = [(self.dir / f"{P1}.md", {"title": TITLES[P1]}), (self.dir / f"{P2}.md", {"title": TITLES[P2]})]
        atg.picker(items, "Which?")
        markup = self.tg.of("sendMessage")[0]["reply_markup"]
        self.tg.calls.clear()
        out = self.poll([self.tap(1, f"art:a:{atg.short_id(P2)}", mid=950, text="Which?", markup=markup)])
        self.assertEqual(out["articles"], f"a:{P2}")
        kb = self.tg.of("editMessageReplyMarkup")[0]["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(kb), 1)                           # P1's row is still there
        self.assertTrue(kb[0][0]["callback_data"].endswith(atg.short_id(P1)))
        self.assertTrue(any("Approved" in t for t in self.tg.texts()))

    def test_other_chat_is_ignored(self):
        u = self.tap(1, f"art:a:{atg.short_id(P1)}")
        u["callback_query"]["message"]["chat"]["id"] = 999
        out = self.poll([u])
        self.assertEqual(out["articles"], "")
        self.assertEqual(self.tg.calls, [])


class ReplyTests(Base):
    def test_reply_approved_to_card_matches_by_message_id(self):
        out = self.poll([self.reply(1, "Approved", {"message_id": 111, "text": "anything"})])
        self.assertEqual(out["articles"], f"a:{P1}")
        self.assertEqual(out["fire"], "0")
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn(TITLES[P1], sent[0]["text"])
        self.assertEqual(sent[0]["reply_parameters"]["message_id"], 5001)
        self.assertNoWhichList()

    def test_reply_words_case_insensitive(self):
        for word, want in (("APPROVE", "a"), ("yes please", "a"), ("ok", "a"), ("👍", "a"),
                           ("Reject", "r"), ("no", "r"), ("NOPE", "r"), ("❌", "r")):
            self.out.write_text("", encoding="utf-8")
            out = self.poll([self.reply(1, word, {"message_id": 111})])
            self.assertEqual(out["articles"], f"{want}:{P1}", word)

    def test_reply_to_old_single_notice_matches_by_title(self):
        notice = {"message_id": 7, "text": f"📝 1 new BOSS KG DRAFT article(s):\n• {TITLES[P2]}\n\n"
                                           "Reply \"approved\" to publish"}
        out = self.poll([self.reply(1, "yes", notice)])
        self.assertEqual(out["articles"], f"a:{P2}")

    def test_bryce_case_reply_to_already_live_article(self):
        # 2026-11-21 12:25 pm NZ: reply "Approved" to the notice of an article the daily
        # auto-publish had already put live. Before: "Got it, publishing" AND "Which article?".
        notice = {"message_id": 8, "text": f"📝 1 new BOSS KG DRAFT article(s):\n• {TITLES[LIVE]}\n\n"
                                           "Reply \"approved\" to publish"}
        out = self.poll([self.reply(1, "Approved", notice)])
        self.assertEqual(out["articles"], "")
        self.assertEqual(out["fire"], "0")
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("Already live", sent[0]["text"])
        self.assertNotIn("publishing", sent[0]["text"].lower())
        self.assertNoWhichList()

    def test_unmatched_reply_gets_one_picker_with_buttons(self):
        notice = {"message_id": 9, "text": "📝 2 new BOSS KG DRAFT article(s):\n• Unknown A\n• Unknown B"}
        out = self.poll([self.reply(1, "approved", notice)])
        self.assertEqual(out["articles"], "")
        self.assertEqual(out["fire"], "0")
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("couldn't tell which", sent[0]["text"])
        self.assertEqual(len(sent[0]["reply_markup"]["inline_keyboard"]), 2)   # P1 and P2 only

    def test_reply_to_multi_notice_offers_only_those_drafts(self):
        notice = {"message_id": 9, "text": f"📝 2 new BOSS KG DRAFT article(s):\n• {TITLES[P1]}\n• {TITLES[P2]}"}
        self.poll([self.reply(1, "approved", notice)])
        kb = self.tg.of("sendMessage")[0]["reply_markup"]["inline_keyboard"]
        self.assertEqual({r[0]["callback_data"][-10:] for r in kb}, {atg.short_id(P1), atg.short_id(P2)})

    def test_no_picker_alongside_a_match(self):
        notice = {"message_id": 9, "text": "📝 2 new BOSS KG DRAFT article(s):\n• Unknown A\n• Unknown B"}
        out = self.poll([self.reply(1, "approved", notice), self.reply(2, "approved", {"message_id": 111})])
        self.assertEqual(out["articles"], f"a:{P1}")
        self.assertNoWhichList()

    def test_yes_to_an_unrelated_bot_message_does_nothing(self):
        out = self.poll([self.reply(1, "yes", {"message_id": 3, "text": "TikTok caption #GTA6"})])
        self.assertEqual(out["articles"], "")
        self.assertEqual(out["fire"], "0")
        self.assertEqual(self.tg.calls, [])


class TextCommandTests(Base):
    def test_approve_all_still_works(self):
        out = self.poll([self.text(1, "approve all")])
        self.assertEqual((out["fire"], out["kind"], out["arg"]), ("1", "approve", "all"))
        self.assertIn("all 2 pending drafts", self.tg.of("sendMessage")[0]["text"])

    def test_approve_keyword_still_works(self):
        out = self.poll([self.text(1, "approve heist mode")])
        self.assertEqual((out["fire"], out["kind"], out["arg"]), ("1", "approve", "heist mode"))
        self.assertIn(TITLES[P1], self.tg.of("sendMessage")[0]["text"])

    def test_approve_all_as_reply_is_the_bulk_command(self):
        out = self.poll([self.reply(1, "approve all", {"message_id": 111})])
        self.assertEqual((out["kind"], out["arg"], out["articles"]), ("approve", "all", ""))

    def test_unmatched_keyword_does_not_say_publishing(self):
        out = self.poll([self.text(1, "approve zelda")])
        self.assertEqual((out["fire"], out["kind"]), ("1", "approve"))
        self.assertEqual(self.tg.of("sendMessage"), [])        # publish step sends the picker only


class PublishActionTests(Base):
    def run_pa(self, *args):
        with mock.patch.object(sys, "argv", ["publish_article.py", *args]):
            return pa.main()

    def test_actions_reject_marks_rejected_and_commits_without_deploy(self):
        with mock.patch.object(pa, "_git_publish") as gp, mock.patch.object(pa, "_publish") as pub:
            self.run_pa("--actions", f"r:{P1}")
        fm, _ = atg.parse(self.dir / f"{P1}.md")
        self.assertIs(fm.get("rejected"), True)
        self.assertIs(fm.get("draft"), True)                   # never shown on the site
        self.assertFalse(gp.call_args.kwargs.get("deploy", True))
        pub.assert_not_called()
        self.assertNotIn(P1, [p.stem for p, _, _ in pa._pending()])

    def test_actions_approve_publishes_only_pending(self):
        with mock.patch.object(pa, "_publish", return_value=0) as pub:
            self.run_pa("--actions", f"a:{P1} a:{LIVE} a:{REJ}")
        targets = pub.call_args.args[0]
        self.assertEqual([p.stem for p, _, _ in targets], [P1])

    def test_actions_on_live_article_does_nothing(self):
        with mock.patch.object(pa, "_publish") as pub, mock.patch.object(pa, "_git_publish") as gp:
            self.run_pa("--actions", f"a:{LIVE}")
        pub.assert_not_called()
        gp.assert_not_called()
        self.assertEqual(self.tg.calls, [])

    def test_publish_dry_run_marks_nothing(self):
        with mock.patch.object(pa, "_captions", return_value={"facebook": "f", "threads": "t"}):
            self.run_pa("--actions", f"a:{P1}", "--dry")
        fm, _ = atg.parse(self.dir / f"{P1}.md")
        self.assertIs(fm.get("draft"), True)
        self.assertEqual(self.tg.calls, [])

    def test_unmatched_text_approve_sends_one_picker(self):
        self.run_pa("--match", "zelda")
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("Which article? Tap one", sent[0]["text"])
        self.assertEqual(len(sent[0]["reply_markup"]["inline_keyboard"]), 2)


class ReviewFixTests(Base):
    """Fixes from the independent review, 2026-11-21."""

    def test_tap_on_draft_not_pushed_yet_keeps_buttons(self):
        out = self.poll([self.tap(1, "art:a:abcdef1234", markup=atg.buttons("not-on-main-yet"))])
        self.assertEqual(out["articles"], "")
        self.assertEqual(self.tg.of("editMessageText"), [])     # card still tappable
        self.assertEqual(self.tg.of("editMessageReplyMarkup"), [])
        self.assertIn("still being saved", self.tg.of("answerCallbackQuery")[0]["text"])

    def test_reply_to_card_not_pushed_yet_says_try_again(self):
        card = {"message_id": 333, "text": "📝 New BOSS KG draft article\n• Brand New Story",
                "reply_markup": atg.buttons("brand-new-story")}
        out = self.poll([self.reply(1, "approved", card)])
        self.assertEqual(out["articles"], "")
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("still being saved", sent[0]["text"])
        self.assertNoWhichList()

    def test_ok_to_a_render_message_does_nothing(self):
        for text in ("🎬 Got it — rendering an IG draft (gta6). It'll land in drafts/ig in a couple minutes…",
                     "📰 Daily blog: no fresh draft today, so nothing was auto-published."):
            self.tg.calls.clear()
            out = self.poll([self.reply(1, "ok", {"message_id": 44, "text": text})])
            self.assertEqual((out["articles"], out["fire"]), ("", "0"))
            self.assertEqual(self.tg.calls, [], text)

    def test_tap_and_typed_approve_same_article_one_batch(self):
        out = self.poll([self.tap(1, f"art:a:{atg.short_id(P1)}", markup=atg.buttons(P1)),
                         self.text(2, "approve heist mode")])
        self.assertEqual(out["articles"], f"a:{P1}")
        self.assertEqual(out["fire"], "0")                      # the typed command adds nothing
        for t in self.tg.texts():
            self.assertNotIn("Got it", t)

    def test_publish_skips_when_another_run_already_published(self):
        path = self.dir / f"{P1}.md"
        target = (path, *pa._parse(path))
        path.write_text(path.read_text(encoding="utf-8").replace("draft: true", "draft: false"),
                        encoding="utf-8")                       # the auto-publish got there first
        with mock.patch.object(pa, "_run", return_value=(0, "")), \
                mock.patch.object(pa, "_git_publish") as gp, mock.patch.object(pa, "_post") as post, \
                mock.patch.object(pa, "_captions") as caps:
            pa._publish([target], dry=False)
        gp.assert_not_called()
        post.assert_not_called()
        caps.assert_not_called()

    def test_auto_pick_uses_this_runs_draft_list(self):
        import datetime as dt
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        for s in (P1, P2):
            p = self.dir / f"{s}.md"
            p.write_text(p.read_text(encoding="utf-8").replace("date: 2026-11-20", f"date: {today}"),
                         encoding="utf-8")
        lst = self.dir / "new_drafts.txt"
        lst.write_text(f"{P2}\n{P1}\n", encoding="utf-8")        # P2 was this run's best pick
        with mock.patch.object(pa, "NEW_DRAFTS", lst), mock.patch.object(pa, "_run", return_value=(0, "")), \
                mock.patch.object(pa, "_publish", return_value=0) as pub, \
                mock.patch.object(sys, "argv", ["publish_article.py", "--auto"]):
            pa.main()
        self.assertEqual(pub.call_args.args[0][0][0].stem, P2)
        self.assertIn("Auto-published", pub.call_args.args[2])


class ListenTests(Base):
    """2026-11-25: taps were answered 2-5 min late; the poller now long-polls and acts at once."""

    def poll_listen(self, batches, listen="30"):
        calls = []

        def fake_tg(method, **params):
            calls.append(params)
            if params.get("offset"):
                return {}
            return {"result": batches.pop(0) if batches else []}
        with mock.patch.object(poller, "_tg", fake_tg), \
                mock.patch.object(sys, "argv", ["x", "--check", "--listen", listen]):
            poller.main()
        out = dict(ln.partition("=")[::2] for ln in self.out.read_text(encoding="utf-8").splitlines())
        return out, calls

    def test_tap_arriving_while_listening_is_answered_at_once(self):
        tap = self.tap(7, f"art:a:{atg.short_id(P1)}", markup=atg.buttons(P1))
        out, calls = self.poll_listen([[], [], [tap]])
        self.assertEqual(out["articles"], f"a:{P1}")
        self.assertTrue(all(0 < c["timeout"] <= 25 for c in calls if "offset" not in c))
        self.assertEqual(len([c for c in calls if "offset" not in c]), 3)   # stopped on the tap
        self.assertEqual(len(self.tg.of("answerCallbackQuery")), 1)
        self.assertIn("Approved", self.tg.of("editMessageText")[0]["text"])

    def test_quiet_listen_ends_with_no_updates(self):
        out, calls = self.poll_listen([], listen="1")
        self.assertEqual((out["fire"], out.get("articles", "")), ("0", ""))
        self.assertEqual(self.tg.calls, [])


class ExpireTests(Base):
    """Bryce, 2026-11-21: "Yes, auto-reject old" (drafts older than 7 days)."""

    def test_expire_rejects_only_old_drafts_and_sends_one_summary(self):
        old = self.dir / f"{P1}.md"                             # has a card (message 111)
        old.write_text(old.read_text(encoding="utf-8").replace("date: 2026-11-20", "date: 2026-09-01"),
                       encoding="utf-8")
        import datetime as dt
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        new = self.dir / f"{P2}.md"
        new.write_text(new.read_text(encoding="utf-8").replace("date: 2026-11-20", f"date: {today}"),
                       encoding="utf-8")
        with mock.patch.object(pa, "_git_publish") as gp, \
                mock.patch.object(sys, "argv", ["publish_article.py", "--expire", "7"]):
            pa.main()
        self.assertIs(atg.parse(old)[0].get("rejected"), True)
        self.assertIs(atg.parse(old)[0].get("draft"), True)     # kept, never shown on the site
        self.assertIsNone(atg.parse(new)[0].get("rejected"))
        self.assertFalse(gp.call_args.kwargs["deploy"])
        self.assertEqual([p.stem for p in gp.call_args.args[0]], [P1])
        self.assertIn("Auto-rejected", self.tg.of("editMessageText")[0]["text"])   # its card
        sent = self.tg.of("sendMessage")
        self.assertEqual(len(sent), 1)
        self.assertIn("Auto-rejected 1 draft", sent[0]["text"])

    def test_expire_nothing_old_is_silent(self):
        with mock.patch.object(pa, "_git_publish") as gp, \
                mock.patch.object(sys, "argv", ["publish_article.py", "--expire", "3650"]):
            pa.main()
        gp.assert_not_called()
        self.assertEqual(self.tg.calls, [])


class CardTests(Base):
    def test_send_card_has_buttons_and_records_message_id(self):
        mid = atg.send_card(self.dir / f"{P2}.md")
        sent = self.tg.of("sendMessage")[0]
        self.assertIn(TITLES[P2], sent["text"])
        for b in sent["reply_markup"]["inline_keyboard"][0]:
            self.assertLessEqual(len(b["callback_data"].encode()), 64)
        fm, _ = atg.parse(self.dir / f"{P2}.md")
        self.assertEqual(fm.get("telegramMessageId"), mid)
        self.assertEqual(atg.find_by_message(mid), self.dir / f"{P2}.md")
        self.assertEqual(fm.get("title"), TITLES[P2])          # rest of frontmatter intact

    def test_long_slug_fits_callback_limit(self):
        slug = "x" * 150
        for b in atg.buttons(slug)["inline_keyboard"][0]:
            self.assertLessEqual(len(b["callback_data"].encode()), 64)

    def test_mark_card_after_publish(self):
        atg.mark_card(self.dir / f"{P1}.md", "✅ Published: https://bosskg.com/news/x")
        e = self.tg.of("editMessageText")[0]
        self.assertEqual(e["message_id"], 111)
        self.assertIn("Published", e["text"])
        self.assertNotIn("reply_markup", e)


if __name__ == "__main__":
    unittest.main()
