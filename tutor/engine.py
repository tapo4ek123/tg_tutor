import asyncio
import re
from dataclasses import dataclass, field

from tutor.budget import BudgetLimitError
from tutor.llm import ModelError, TutorModel
from tutor.models import Attempt, Diagnostic, Grade, LearningState, Lesson, Plan, StrictModel


class Explanation(StrictModel):
    text: str


@dataclass
class Reply:
    text: str
    actions: list[str] = field(default_factory=list)
    revision: int = 0
    action_labels: dict[str, str] = field(default_factory=dict)


PROFILE_CHOICES = {
    "experience_zero": ("experience", "Начинаю с нуля", "Начинаю с нуля"),
    "experience_basic": ("experience", "Есть базовые знания", "Есть базовые знания"),
    "time_short": ("budget", "15 3", "15 минут · 3 раза в неделю"),
    "time_regular": ("budget", "30 3", "30 минут · 3 раза в неделю"),
    "time_intensive": ("budget", "45 5", "45 минут · 5 раз в неделю"),
    "deadline_none": ("deadline", "без срока", "Без срока"),
    "deadline_month": ("deadline", "Через месяц", "Через месяц"),
}


HELP = """Я SkillPilot — тьютор для самостоятельного обучения.

Основные действия доступны на клавиатуре под полем ввода.
«Продолжить» возвращает к текущему шагу, «Мои навыки» переключает направление.
«Скрыть меню» убирает клавиатуру; /menu возвращает её.
В задании обычное сообщение — ответ на проверку. Для вопроса нажмите «Задать вопрос».

/start — вернуться к текущему шагу
/menu — главное меню
/continue — продолжить обучение
/skills — мои навыки и переключение
/newskill [цель] — добавить навык
/switch ID — выбрать навык из списка
/budget — общий суточный расход модели
/plan — учебный план
/lesson — занятие или текущее задание
/hint — следующая подсказка
/ask вопрос — объяснение по теме (учитывается как помощь)
/cancel — выйти из режима вопроса
/progress — результаты и изменения плана
/remind 19:00 Europe/Moscow 1,3,5 — напоминания (1=пн, 7=вс)
/remind off — отключить напоминания
/snooze — напомнить через час
/reset — удалить выбранный навык с подтверждением

Ответ на задание отправляйте обычным сообщением. Код проверяю по тексту,
без исполнения. Финальную работу нужно пройти без подсказок.
Ответы и прогресс сохраняются на сервере; для обучения текст передаётся провайдеру LLM.
"""


def grade_score(lesson: Lesson, grade: Grade) -> float:
    if [item.criterion for item in grade.criteria] != lesson.rubric:
        raise ModelError("Модель изменила критерии проверки. Отправьте ответ ещё раз.")
    return sum(item.score for item in grade.criteria) / (2 * len(lesson.rubric))


class TutorEngine:
    def __init__(self, tools, model: TutorModel):
        self.tools = tools
        self.model = model

    async def handle(self, user_id: int, text: str, expected_revision: int | None = None) -> Reply:
        snapshot = await self.tools.call("get_learning_state", user_id=user_id)
        state = LearningState.model_validate(snapshot["state"])
        if expected_revision is not None and snapshot["revision"] != expected_revision:
            return self.resume_reply(
                state, snapshot["revision"], "Это меню уже устарело. Вот текущий шаг."
            )
        text = text.strip()
        if text == "/lesson" and state.input_mode == "question":
            text = "/cancel"
        if text == "/continue":
            if state.pending_request:
                text = "/budget_resume"
            elif state.input_mode == "question":
                text = "/cancel"
            else:
                text = {"learning": "/lesson", "plan_review": "/plan"}.get(state.stage, "/resume")
        if not text.startswith("/") and state.input_mode == "question":
            text = "/ask " + text
        if text.strip() == "/budget":
            return await self.budget_reply(state, snapshot["revision"])
        if text.strip() == "/budget_resume":
            if not state.pending_request:
                return await self.budget_reply(state, snapshot["revision"])
            text = state.pending_request
        try:
            return await self._handle(user_id, text, expected_revision, snapshot)
        except BudgetLimitError as exc:
            state.pending_request = text
            saved = await self.tools.call(
                "save_learning_state",
                user_id=user_id,
                revision=snapshot["revision"],
                state=state.model_dump(),
            )
            return self.reply(str(exc), state, saved["revision"])

    async def budget_reply(self, state: LearningState, revision: int) -> Reply:
        ledger = getattr(self.model, "budget", None)
        if ledger is None:
            return self.reply("Учёт расхода доступен при подключённой модели.", state, revision)
        status = await asyncio.to_thread(ledger.status)
        message = (
            f"Общий бюджет приложения: ${float(status['limit_usd']):.2f} в сутки.\n"
            f"Расход: ${float(status['spent_usd']):.6f}\n"
            f"В резерве: ${float(status['reserved_usd']):.6f}\n"
            f"Осталось: ${float(status['remaining_usd']):.6f}\n"
            f"Сброс: {status['reset_at']}\n"
            "Учитываются все пользователи и навыки этого приложения. "
            "Расходы других приложений аккаунта не включены."
        )
        return self.reply(message, state, revision)

    async def _handle(self, user_id: int, text: str, expected_revision, snapshot: dict) -> Reply:
        state = LearningState.model_validate(snapshot["state"])
        revision = snapshot["revision"]
        text = text.strip()
        if expected_revision is not None and revision != expected_revision:
            return self.reply(
                "Это меню уже устарело. Продолжим с текущего состояния.", state, revision
            )
        if len(text) > 10000:
            return self.reply("Сократите сообщение до 10 000 символов.", state, revision)
        if text.startswith("/choose "):
            choice = PROFILE_CHOICES.get(text.partition(" ")[2])
            if choice is None or choice[0] != state.stage:
                return self.resume_reply(state, revision, "Этот вариант уже не относится к шагу.")
            text = choice[1]
        if text in {"/menu", "/home"}:
            return self.home_reply(state, revision)
        if text in {"/start", "/resume"}:
            welcome = (
                "Я SkillPilot. Помогу выбрать маршрут, практиковаться и замечать прогресс.\n"
                "Сначала настроим навык: цель → опыт → время → срок, затем диагностика и план.\n"
                "Учебные ответы передаются провайдеру модели и сохраняются на сервере."
                if not state.goal
                else "Продолжим с того места, где остановились."
            )
            return self.resume_reply(state, revision, welcome)
        if text == "/back":
            previous = {"experience": "goal", "budget": "experience", "deadline": "budget"}
            if state.stage not in previous:
                return self.resume_reply(state, revision)
            state.stage = previous[state.stage]
            state.pending_request = None
            saved = await self.tools.call(
                "save_learning_state", user_id=user_id, revision=revision, state=state.model_dump()
            )
            return self.resume_reply(state, saved["revision"], "Можно изменить предыдущий ответ.")
        if text in {"/ask", "/cancel"}:
            if not state.lesson:
                return self.resume_reply(state, revision, "Сначала откройте занятие.")
            state.input_mode = "question" if text == "/ask" else "answer"
            if text == "/cancel" and (state.pending_request or "").startswith("/ask "):
                state.pending_request = None
            saved = await self.tools.call(
                "save_learning_state", user_id=user_id, revision=revision, state=state.model_dump()
            )
            return self.resume_reply(state, saved["revision"])
        if text == "/skills" or text.startswith("/skills "):
            page = text.split(maxsplit=1)[1] if " " in text else "1"
            if not page.isdigit() or len(page) > 6:
                return self.reply("Список навыков: /skills", state, revision)
            return await self.skills_reply(user_id, int(page))
        if text == "/newskill" or text.startswith("/newskill "):
            goal = text.partition(" ")[2].strip()
            if goal and len(goal) < 5:
                return self.reply(
                    "Опишите новый навык чуть подробнее: /newskill Хочу выучить испанский",
                    state,
                    revision,
                )
            created = await self.tools.call(
                "create_skill", user_id=user_id, revision=revision, goal=goal
            )
            new_state = LearningState.model_validate(created["state"])
            return self.reply(
                "Новый навык выбран. " + self.stage_prompt(new_state),
                new_state,
                created["revision"],
            )
        if text == "/switch" or text.startswith("/switch "):
            skill_id = text.partition(" ")[2].strip()
            if not skill_id.isdigit() or len(skill_id) > 19 or not 0 < int(skill_id) < 2**63:
                return self.reply(
                    "Выберите навык через /skills или введите /switch ID.", state, revision
                )
            selected = await self.tools.call(
                "switch_skill", user_id=user_id, skill_id=int(skill_id), revision=revision
            )
            if selected.get("error"):
                return self.reply("Навык не найден. Ваш список: /skills", state, revision)
            new_state = LearningState.model_validate(selected["state"])
            return self.resume_reply(new_state, selected["revision"], "Навык выбран.")
        if text == "/reset":
            return Reply(
                f"Удалить навык «{state.goal[:100] or 'Новый навык'}», его задания и прогресс? "
                "Остальные навыки сохранятся.",
                ["reset_confirm", "home"],
                revision,
                {"home": "Отмена"},
            )
        if text == "/reset_confirm":
            if expected_revision is None:
                return self.reply(
                    "Для сброса используйте /reset и кнопку подтверждения.", state, revision
                )
            selected = await self.tools.call(
                "reset_learning_state", user_id=user_id, revision=revision
            )
            new_state = LearningState.model_validate(selected["state"])
            return self.reply(
                "Навык удалён. " + self.stage_prompt(new_state), new_state, selected["revision"]
            )
        if text == "/help":
            return self.reply(HELP, state, revision)
        if text == "/plan":
            return self.reply(self.format_plan(state), state, revision)
        if text == "/progress":
            return self.reply(self.format_progress(state), state, revision)

        profile = {
            "goal": state.goal,
            "experience": state.experience,
            "minutes_per_session": state.minutes_per_session,
            "sessions_per_week": state.sessions_per_week,
            "deadline": state.deadline,
        }
        if text == "/accept":
            if state.stage != "plan_review":
                return self.reply(self.stage_prompt(state), state, revision)
            state.stage = "learning"
            message = "План принят. Нажмите «Начать занятие», когда будете готовы."
        elif text == "/lesson":
            if state.stage != "learning":
                return self.reply(self.stage_prompt(state), state, revision)
            if state.lesson:
                return self.reply(self.format_lesson(state.lesson), state, revision)
            assert state.plan
            resources = await self.tools.call("search_materials", query=state.goal)
            state.lesson = await self.model.generate(
                "lesson",
                Lesson,
                {
                    "profile": profile,
                    "plan": state.plan.model_dump(),
                    "module_index": state.module_index,
                    "module": state.plan.modules[state.module_index].model_dump(),
                    "focus": state.focus,
                    "recent_attempts": [a.model_dump() for a in state.attempts[-3:]],
                    "final": state.module_index == len(state.plan.modules) - 1,
                    "materials": resources["materials"],
                },
            )
            state.hints_used = 0
            message = self.format_lesson(state.lesson)
            if resources["materials"]:
                message += "\n\nМатериалы:\n" + "\n".join(
                    f"{item['title']}: {item['url']}" for item in resources["materials"]
                )
        elif text == "/hint":
            if not state.lesson:
                return self.reply("Сначала начните занятие: /lesson", state, revision)
            if state.hints_used >= 3:
                return self.reply(
                    "Все три подсказки показаны. "
                    "Задайте вопрос через /ask или попробуйте ответить.",
                    state,
                    revision,
                )
            message = f"Подсказка {state.hints_used + 1}/3:\n{state.lesson.hints[state.hints_used]}"
            state.hints_used += 1
        elif text.startswith("/ask "):
            if not state.lesson:
                return self.reply("Сначала начните занятие: /lesson", state, revision)
            answer = await self.model.generate(
                "ask",
                Explanation,
                {
                    "profile": profile,
                    "lesson": {
                        "title": state.lesson.title,
                        "explanation": state.lesson.explanation,
                        "task": state.lesson.task,
                    },
                    "question": text[5:],
                },
            )
            state.hints_used = min(state.hints_used + 1, 3)
            state.input_mode = "answer"
            message = (
                answer.text + "\n\nЭто объяснение учтено как помощь в текущем задании.\n"
                "Теперь можно отправить ответ на задание или задать ещё один вопрос кнопкой."
            )
        elif text.startswith("/"):
            return self.reply("Неизвестная команда. Список: /help", state, revision)
        elif state.stage == "goal":
            if len(text) < 5:
                return self.reply(
                    "Опишите навык и желаемый результат чуть подробнее.", state, revision
                )
            state.goal = text
            state.stage = "experience"
            message = self.stage_prompt(state)
        elif state.stage == "experience":
            state.experience = text
            state.stage = "budget"
            message = self.stage_prompt(state)
        elif state.stage == "budget":
            match = re.fullmatch(r"\s*(\d{1,3})[ ,;]+(\d)\s*", text)
            if not match or not (5 <= int(match[1]) <= 120 and 1 <= int(match[2]) <= 7):
                return self.reply(
                    "Введите минуты и занятия в неделю: например 30 3. "
                    "Минуты: 5–120, занятия: 1–7.",
                    state,
                    revision,
                )
            state.minutes_per_session, state.sessions_per_week = map(int, match.groups())
            state.stage = "deadline"
            message = self.stage_prompt(state)
        elif state.stage == "deadline":
            state.deadline = text
            profile["deadline"] = text
            state.diagnostic = await self.model.generate("diagnostic", Diagnostic, profile)
            state.stage = "diagnostic"
            message = self.stage_prompt(state)
        elif state.stage == "diagnostic":
            assert state.diagnostic
            state.diagnostic_answer = text
            state.plan = await self.model.generate(
                "plan",
                Plan,
                {
                    "profile": profile,
                    "diagnostic": state.diagnostic.model_dump(),
                    "answer": text,
                },
            )
            if any(module.minutes > state.minutes_per_session for module in state.plan.modules):
                raise ModelError("Модель превысила бюджет занятия. Повторите ответ на диагностику.")
            state.stage = "plan_review"
            message = self.format_plan(state) + "\n\nНажмите «Принять план» для начала."
        elif state.stage == "learning" and state.lesson:
            assert state.plan
            grade = await self.model.generate(
                "grade",
                Grade,
                {
                    "lesson": state.lesson.model_dump(),
                    "answer": text,
                },
            )
            score = grade_score(state.lesson, grade)
            final = state.module_index == len(state.plan.modules) - 1
            passed = score >= 0.8 and not (final and state.hints_used > 0)
            state.attempts.append(
                Attempt(
                    module_index=state.module_index,
                    task=state.lesson.task,
                    answer=text,
                    score=score,
                    passed=passed,
                    hints_used=state.hints_used,
                    feedback=grade.feedback,
                    gaps=grade.gaps,
                )
            )
            message = f"Результат задания: {score:.0%}\n\n" + grade.feedback
            if passed:
                state.module_index += 1
                state.focus = []
                if state.module_index == len(state.plan.modules):
                    state.stage = "done"
                    message += (
                        "\n\nЦель по критериям плана достигнута! "
                        "Итоговая работа пройдена без подсказок."
                    )
                else:
                    message += "\n\nЭтап пройден. Следующий: /lesson"
            else:
                gaps = grade.gaps or ["Повторить критерии текущего задания"]
                if final and state.hints_used:
                    gaps = ["Выполнить итоговую работу самостоятельно, без подсказок", *gaps]
                state.focus = gaps
                note = f"Этап {state.module_index + 1}: добавлена практика — " + "; ".join(gaps)
                state.adaptations.append(note)
                message += "\n\nПлан скорректирован: " + note + "\nНовое задание: /lesson"
            state.lesson = None
            state.hints_used = 0
        else:
            return self.reply(self.stage_prompt(state), state, revision)

        state.pending_request = None
        saved = await self.tools.call(
            "save_learning_state",
            user_id=user_id,
            revision=revision,
            state=state.model_dump(),
        )
        return self.reply(message, state, saved["revision"])

    @staticmethod
    def reply(text: str, state: LearningState, revision: int) -> Reply:
        actions = []
        labels = {}
        if state.stage == "plan_review":
            actions = ["accept", "plan"]
        elif state.stage == "learning":
            if state.input_mode == "question":
                actions = ["cancel"]
                text += "\n\nЖду вопрос по занятию. Это сообщение не будет оцениваться как ответ."
            elif state.lesson:
                actions = ["lesson", *(["hint"] if state.hints_used < 3 else []), "ask"]
                labels["lesson"] = "Вернуться к заданию"
            else:
                actions = ["lesson", "progress"]
                labels["lesson"] = (
                    "Новое задание по пробелам"
                    if state.focus
                    else "Следующее занятие"
                    if state.module_index
                    else "Начать занятие"
                )
        elif state.stage == "done":
            actions = ["newskill", "skills", "progress"]
        else:
            for slug, (stage, _, label) in PROFILE_CHOICES.items():
                if stage == state.stage:
                    action = "choose_" + slug
                    actions.append(action)
                    labels[action] = label
            if state.stage in {"experience", "budget", "deadline"}:
                actions.append("back")
        if "skills" not in actions:
            actions.append("skills")
        actions.append("home")
        if state.pending_request:
            actions.insert(0, "budget_resume")
        if state.goal:
            text = f"Навык: {state.goal[:100]}\n{TutorEngine.stage_label(state)}\n\n" + text
        return Reply(text, actions, revision, labels)

    @staticmethod
    def stage_label(state: LearningState) -> str:
        if state.stage == "learning" and state.plan:
            return f"Занятие {state.module_index + 1} из {len(state.plan.modules)}"
        return {
            "goal": "Настройка · 1/4: цель",
            "experience": "Настройка · 2/4: опыт",
            "budget": "Настройка · 3/4: время",
            "deadline": "Настройка · 4/4: срок",
            "diagnostic": "Диагностика перед планом",
            "plan_review": "План готов к подтверждению",
            "done": "Обучение по плану завершено",
        }.get(state.stage, "Обучение")

    @staticmethod
    def resume_reply(state: LearningState, revision: int, prefix: str = "") -> Reply:
        if state.input_mode == "question" and state.lesson:
            message = (
                "Напишите, что непонятно в занятии. Чтобы отправить решение, нажмите «К заданию»."
            )
        elif state.stage == "learning" and state.lesson:
            message = TutorEngine.format_lesson(state.lesson)
        elif state.stage == "plan_review":
            message = (
                TutorEngine.format_plan(state) + "\n\nЕсли маршрут подходит, примите план кнопкой."
            )
        else:
            message = TutorEngine.stage_prompt(state)
        if state.pending_request:
            message += (
                "\n\nЕсть сохранённое действие после остановки по бюджету. "
                "Кнопка ниже проверит лимит."
            )
        return TutorEngine.reply((prefix + "\n\n" if prefix else "") + message, state, revision)

    @staticmethod
    def home_reply(state: LearningState, revision: int) -> Reply:
        if not state.goal:
            return TutorEngine.resume_reply(state, revision, "Главное меню · начнём с цели.")
        message = (
            "Главное меню\n\n"
            f"Навык: {state.goal[:100]}\n{TutorEngine.stage_label(state)}\n\n"
            "«Продолжить» откроет текущий шаг. «Мои навыки» — выбор другого направления."
        )
        if state.plan:
            message += f"\nПройдено этапов: {state.module_index}/{len(state.plan.modules)}."
        if state.input_mode == "question":
            message += "\nСейчас открыт ввод вопроса. «Продолжить» вернёт к решению задания."
        if state.pending_request:
            message += "\nЕсть сохранённое действие. Кнопка ниже проверит лимит и продолжит его."
        primary = "budget_resume" if state.pending_request else "continue"
        actions = [primary, "skills", "newskill", "remind"]
        if state.stage == "done":
            actions = ["skills", "newskill", "progress", "remind"]
        return Reply(message, actions, revision)

    async def skills_reply(self, user_id: int, page: int = 1) -> Reply:
        catalog = await self.tools.call("list_skills", user_id=user_id)
        skills = sorted(
            catalog["skills"], key=lambda item: (item["stage"] == "done", item["skill_id"])
        )
        pages = max(1, (len(skills) + 9) // 10)
        page = min(max(1, page), pages)
        visible = skills[(page - 1) * 10 : page * 10]
        lines = ["Мои навыки", "Выберите навык, чтобы продолжить его план и задания."]
        actions, labels = [], {}
        for skill in visible:
            skill_id = skill["skill_id"]
            title = skill["goal"] or f"Новый навык #{skill_id}"
            selected = skill_id == catalog["active_skill_id"]
            mark = "→" if selected else "✓" if skill["stage"] == "done" else "○"
            progress = (
                f"{skill['module_index']}/{skill['module_count']} этапов"
                if skill["module_count"]
                else "настройка обучения"
            )
            if skill["stage"] == "done":
                progress += ", завершён"
            lines.append(f"{mark} #{skill_id}. {title[:120]} — {progress}")
            action = f"switch_{skill_id}"
            actions.append(action)
            labels[action] = f"{mark} {title[:45]}"
        if not skills:
            lines.append("Навыков пока нет. Добавьте первый через /newskill или расскажите о цели.")
        if pages > 1:
            lines.append(f"Страница {page}/{pages}")
            for target, label in [(page - 1, "← Назад"), (page + 1, "Далее →")]:
                if 1 <= target <= pages:
                    action = f"skills_page_{target}"
                    actions.append(action)
                    labels[action] = label
        actions.extend(["newskill", "home"])
        return Reply("\n\n".join(lines), actions, catalog["revision"], labels)

    @staticmethod
    def stage_prompt(state: LearningState) -> str:
        prompts = {
            "goal": (
                "Шаг 1/4. Какой навык хотите освоить? Опишите желаемый результат.\n"
                "Например: «Освоить Go и написать первую CLI-программу»."
            ),
            "experience": (
                "Шаг 2/4. Какой у вас опыт по этой теме? Что уже умеете?\n"
                "Выберите вариант ниже или расскажите своими словами."
            ),
            "budget": (
                "Шаг 3/4. Сколько минут на занятие и занятий в неделю?\n"
                "Выберите вариант ниже или введите два числа. Например: 30 3"
            ),
            "deadline": (
                "Шаг 4/4. К какому сроку хотите достичь цели?\n"
                "Можно написать дату или выбрать «Без срока». После этого начнётся диагностика."
            ),
            "plan_review": "План готов. Посмотрите /plan и нажмите «Принять план».",
            "learning": (
                "Отправьте ответ на задание обычным сообщением. Для вопроса есть отдельная кнопка."
            )
            if state.lesson
            else (
                "Следующий шаг — занятие. Нажмите кнопку ниже, чтобы получить объяснение и задание."
            ),
            "done": (
                "Цель по плану достигнута. Результаты: /progress. "
                "Другой навык: /skills. Новый: /newskill"
            ),
        }
        if state.stage == "diagnostic" and state.diagnostic:
            return (
                state.diagnostic.introduction
                + "\n\n"
                + "\n".join(f"{i}. {q}" for i, q in enumerate(state.diagnostic.questions, 1))
                + "\n\nОтветьте одним сообщением по номерам. Можно написать «не знаю»."
            )
        return prompts.get(state.stage, "Продолжим: /start")

    @staticmethod
    def format_plan(state: LearningState) -> str:
        if not state.plan:
            return "Плана пока нет. " + TutorEngine.stage_prompt(state)
        plan = state.plan
        lines = [f"Цель: {plan.goal}", plan.diagnostic_feedback, plan.feasibility_note, ""]
        for i, module in enumerate(plan.modules):
            mark = "✓" if i < state.module_index else "→" if i == state.module_index else "○"
            lines.append(f"{mark} {i + 1}. {module.title} · {module.minutes} мин\n{module.outcome}")
        lines += ["", "Итоговая работа: " + plan.final_challenge]
        if state.adaptations:
            lines += ["", "Дополнительная практика:", *state.adaptations[-5:]]
        return "\n".join(lines)

    @staticmethod
    def format_lesson(lesson: Lesson) -> str:
        return (
            f"{lesson.title}\n\n{lesson.explanation}\n\nПример:\n{lesson.example}"
            f"\n\nЗадание:\n{lesson.task}" + "\n\nОтправьте решение одним сообщением. "
            "Если нужна помощь, нажмите «Подсказка» или «Задать вопрос»."
        )

    @staticmethod
    def format_progress(state: LearningState) -> str:
        if not state.plan:
            return "Прогресс появится после диагностики и создания плана. /start"
        count = len(state.plan.modules)
        passed = sum(a.passed for a in state.attempts)
        result = (
            f"Цель: {state.plan.goal}\nПройдено этапов: {state.module_index}/{count} "
            f"({state.module_index / count:.0%} плана)\nПопыток: {len(state.attempts)}, "
            f"успешных: {passed}\nЭто прогресс по плану, а не процент знания навыка."
        )
        if state.attempts:
            result += "\n\nПоследние проверки:\n" + "\n".join(
                f"Этап {a.module_index + 1}: {a.score:.0%}, "
                + ("зачтено" if a.passed else "нужна практика")
                for a in state.attempts[-5:]
            )
        if state.adaptations:
            result += "\n\nИзменения плана:\n" + "\n".join(state.adaptations[-5:])
        return result
