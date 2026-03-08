"""
Base agent for test generation

Uses LangGraph for structured workflows.
"""

import json
import re
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import warnings

from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import HumanMessage, AIMessage

from codecoverage.core.codebase import Codebase
from codecoverage.agents.tools import (
    initialize_tools,
    get_all_tools
)
from codecoverage.llm.providers import create_llm


class TestGenerationAgent:
    """
    Agent for generating tests using LangGraph

    Workflow:
    1. Analyze project patterns
    2. Search for relevant code
    3. Generate test code
    4. Validate and refine
    """

    def __init__(
        self,
        codebase: Codebase,
        project_root: Path,
        llm_config: Dict[str, Any]
    ):
        """
        Initialize test generation agent

        Args:
            codebase: Parsed codebase
            project_root: Project root directory
            llm_config: LLM configuration (model, api_key, temperature)
        """
        self.codebase = codebase
        self.project_root = project_root

        # Initialize LLM via provider factory
        self.llm = create_llm(
            provider=llm_config.get("provider", "anthropic"),
            model=llm_config.get("model"),
            api_key=llm_config.get("api_key"),
            temperature=llm_config.get("temperature", 0.0),
        )

        # Initialize tools
        initialize_tools(codebase, project_root)
        self.tools = get_all_tools()

        # CursorAgentLLM is a one-shot agent — skip LangGraph entirely.
        from codecoverage.llm.providers import CursorAgentLLM
        self._is_cursor = isinstance(self.llm, CursorAgentLLM)

        if not self._is_cursor:
            # Bind tools to LLM
            self.llm_with_tools = self.llm.bind_tools(self.tools)
            # Build graph
            self.graph: CompiledStateGraph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """
        Build LangGraph workflow

        Returns:
            Compiled state graph
        """
        from langgraph.prebuilt import create_react_agent

        # Suppress deprecation warning (we'll upgrade LangGraph later)
        warnings.filterwarnings('ignore', category=DeprecationWarning)

        # Create ReAct agent with tools
        agent = create_react_agent(
            model=self.llm,  # type: ignore
            tools=self.tools,
        )

        return agent

    def generate_test(
        self,
        target_function: str,
        target_file: str,
        additional_context: str = ""
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Generate a test for a specific function.

        Args:
            target_function: Name of function to test
            target_file: File containing the function
            additional_context: Optional additional context

        Returns:
            (test_code, doc) where doc is a dict with summary/behaviors/
            side_effects/test_coverage, or None if the LLM omitted it.
        """
        prompt = self._build_test_generation_prompt(
            target_function,
            target_file,
            additional_context
        )
        if self._is_cursor:
            return self._invoke_cursor(prompt)
        result = self.graph.invoke({
            "messages": [HumanMessage(content=prompt)]
        })
        return self._extract_result(result)

    @staticmethod
    def _build_test_generation_prompt(
        target_function: str,
        target_file: str,
        additional_context: str
    ) -> str:
        """Build the test generation prompt.

        The prompt enforces a strict decision tree:
          module tests exist  →  follow their style exactly
          no module tests     →  fall back to project-wide patterns
          no project patterns →  use standard pytest conventions
        """

        prompt = f"""You are an expert Python test engineer. Your job is to decide \
whether a function is worth testing, and if so, generate a complete, runnable test.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Target function : {target_function}
  Source file     : {target_file}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

────────────────────────────────────────
STEP 0 — Decide whether to test this function at all
────────────────────────────────────────
You are allowed — and expected — to SKIP a function that is not worth testing.
Output a skip decision by writing:

  <skip>one sentence reason</skip>

and NOTHING else (no python block, no <doc> block) when the function falls into
any of these categories:

  • Django / framework entry points with no logic of their own:
      manage.py main(), wsgi.py application, asgi.py application, conftest.py fixtures
  • Single-line passthroughs that only call one other function with no branching
  • Migration files (anything under a migrations/ directory)
  • __str__ / __repr__ / __init__ with only attribute assignment
  • Functions whose entire body is `pass` or a single return of a constant

Also respect the user's own instructions: if the extra context below asks you to
focus on certain areas (e.g. "celery tasks, APIs and models") and this function
clearly falls outside those areas, output a skip decision.

Only proceed to the steps below if the function is genuinely worth testing.

Follow these steps IN ORDER. Do not skip any step.

────────────────────────────────────────
STEP 1 — Study existing module tests  (MANDATORY, always do this first)
────────────────────────────────────────
Call: get_module_test_examples("{target_file}")

This is the most important step. The tool searches for a test file that
already covers this module and returns its complete style information.

Decision rule based on the result:

  A) Tests found → USE THEIR STYLE FOR EVERYTHING:
       • Exact same imports (copy them)
       • Same base class (e.g. TransactionTestCase, BaseTestCase, or custom)
       • Same fixture / setUp pattern
       • Same mocking approach (@patch, mocker.patch, custom @mock decorator, etc.)
       • Same assertion style (assert / self.assertEqual / custom)
       • Same function naming convention
     Do NOT introduce pytest if the project uses unittest. Do NOT introduce
     a new base class. Consistency is the only goal here.

  B) No tests found → the tool says "NO EXISTING TESTS". Move to Step 2.

────────────────────────────────────────
STEP 2 — Project-wide conventions  (only if Step 1 found nothing)
────────────────────────────────────────
Call: analyze_project_patterns()

Use the detected framework, fixture style, and mocking library as defaults
for the test you will generate.  If step 1 DID find tests, skip this step.

────────────────────────────────────────
STEP 3 — Read the ACTUAL source file  (MANDATORY, do not skip)
────────────────────────────────────────
Call: read_source_file("{target_file}")

You MUST read the actual source before writing a single line of test code.
From the source extract:
  • The EXACT class name(s) — do not guess or rename them
  • The EXACT method/function signature (parameters and types)
  • Every field name, type, and constraint (e.g. serializer fields)
  • Every import at the top of the file (reproduce these in your test)
  • Every code branch: happy path, exceptions raised, early returns, None cases
  • Which external services are called (ORM, HTTP, cache, importlib, etc.)

⚠ Never invent class names, field names, or method names.
  Use ONLY names that appear verbatim in the source you just read.

────────────────────────────────────────
STEP 3b — DRF delegation pattern  (apply if the source has `serializer_class`)
────────────────────────────────────────
If the class you just read has a `serializer_class = SomeSerializer` attribute
and little or no method body (typical of DRF generic views), the real business
logic lives in the serializer — NOT in the view itself.

DRF runtime call path for a CreateAPIView POST:
  POST → create() → perform_create(serializer) → serializer.save() → serializer.create()

You MUST also call: read_source_file("<file containing SomeSerializer>")
  • Extract all field definitions (these become the request payload in tests)
  • Extract validate() / validate_<field>() logic (these are the assertion targets)
  • Extract create() (this is where DB writes and side effects happen)

Then test AT THE VIEW LEVEL (dispatch through MyView.as_view()(request)) and
assert the side effects of the serializer's create() — do NOT test the serializer
in isolation unless that is explicitly what was asked.

────────────────────────────────────────
STEP 4 — Map dependencies
────────────────────────────────────────
Call: get_function_dependencies("{target_file}", "{target_function}")

For each dependency decide:
  • Mock it  — if it calls external services, databases, or file I/O
  • Use real  — if it is a pure utility the test can exercise safely

Key rule for @patch targets: patch WHERE the name is looked up (the import
site in the module under test), NOT where it is defined.
Example: if views.py does `from payments.models import GatewayRefund`, patch
         'payments.interface_layer.payment_gateway.views.GatewayRefund',
         NOT 'payments.interface_layer.models.GatewayRefund'.

────────────────────────────────────────
STEP 4b — Identify decoupled flows  (MANDATORY)
────────────────────────────────────────
Call: get_decoupled_flows("{target_file}")

This reveals functions that are NOT called directly by user code — they are
invoked by frameworks, signal dispatchers, task queues, or other runtime
machinery based on their decorator arguments.

Read the output carefully:

  If the target function appears in the decoupled-flows output:
    → It is framework-invoked. Do NOT test it via a direct call from a view
      or serializer. Instead:
        • Call it directly with the data/context structure the framework
          provides (read the decorator definition to understand that structure)
        • OR test it through the framework's public entry point and mock
          downstream side-effects

  Interpreting common decorator patterns (generic — use your judgement):
    @post_transition(order=N)  — state-machine hook, called after DB status
                                  update; receives (self, data, context) where
                                  data contains 'instances' and
                                  'post_transition_responses' dicts
    @pre_transition(order=N)   — state-machine hook, called before DB update;
                                  same signature as post_transition
    @receiver(signal, sender=X) — Django signal handler; call directly with
                                  mock sender/instance kwargs, or trigger by
                                  actually firing the signal in a test
    @shared_task / @app.task   — Celery task; test the underlying function
                                  body directly, mock .delay()/.apply_async()
                                  at every call site that enqueues it
    @pytest.fixture            — not production code; skip or document only

  If the file has NO decoupled flows the tool returns "NO DECOUPLED FLOWS" —
  proceed normally.

────────────────────────────────────────
STEP 5 — Write the test
────────────────────────────────────────
Generate test code that:
  ✓ Perfectly mirrors the style from Step 1 (or Step 2 as fallback)
  ✓ Uses ONLY class/method/field names read from the source in Step 3
  ✓ Covers the happy path
  ✓ Covers at least 2 failure / edge-case paths
  ✓ Has descriptive names explaining *what* is being tested
  ✓ Includes all imports, setup/teardown, and mock configuration
  ✓ Is immediately runnable without any manual edits

Django / DRF rules (apply when rest_framework is imported in the source):
  • Use APIRequestFactory (from rest_framework.test), NOT Django's RequestFactory
    Django's RequestFactory produces WSGIRequest which lacks request.data
  • Dispatch views through MyView.as_view()(request), NOT MyView().method(request)
  • For classmethods on a view, patch with @patch.object(MyView, 'method_name')
  • When mocking a model class, preserve its DoesNotExist exception:
      mock_cls.DoesNotExist = RealModel.DoesNotExist   (before triggering it)
    Without this, the except clause raises TypeError at runtime.

Python version rules:
  • If the project's venv contains cpython-36 .pyc files, target Python 3.6:
      - No walrus operator (:=)
      - call_args[1] instead of call_args.kwargs  (kwargs attr added in 3.8)
      - No positional-only params (/) in function signatures
      - f-string debug syntax (f"{{x=}}") not available

{additional_context}

Output the complete test code in a ```python block.
Immediately after the closing ```, output a behavioural documentation block:

<doc>
{{
  "summary": "One sentence: what this function does and its role in the system",
  "behaviors": ["key observable behavior 1", "behavior 2"],
  "side_effects": ["signals emitted", "tasks enqueued", "DB writes — empty list if none"],
  "test_coverage": "what the generated tests verify"
}}
</doc>

The JSON inside <doc> must be valid. Base it only on what you read in the source.
No other prose outside the code block and the <doc> block.
"""
        return prompt

    def generate_doc(
        self,
        target_function: str,
        target_file: str,
        class_context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Generate behavioural documentation for a function — no test code.

        Lighter prompt than generate_test(): only 3 tool calls, output is
        the <doc> block only. Used by `document --enrich` batch mode.

        Args:
            target_function: Name of the function or method.
            target_file:     Source file path (relative to project root).
            class_context:   Class name if this is a method (for disambiguation).

        Returns:
            Doc dict with summary/behaviors/side_effects, or None on failure.
        """
        prompt = self._build_doc_prompt(target_function, target_file, class_context)
        if self._is_cursor:
            _, doc = self._invoke_cursor(prompt)
            return doc
        result = self.graph.invoke({
            "messages": [HumanMessage(content=prompt)]
        })
        _, doc = self._extract_result(result)
        return doc

    @staticmethod
    def _build_doc_prompt(
        target_function: str,
        target_file: str,
        class_context: str,
    ) -> str:
        class_hint = f" (method of `{class_context}`)" if class_context else ""
        return f"""You are a Python documentation expert. Analyse the function below \
and document its behaviour precisely.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Function : {target_function}{class_hint}
  File     : {target_file}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

────────────────────────────────────────
STEP 1 — Read the source file  (MANDATORY)
────────────────────────────────────────
Call: read_source_file("{target_file}")

Focus on `{target_function}`. Extract its exact signature, all code branches,
what it reads, what it writes, and what it returns or raises.

────────────────────────────────────────
STEP 1b — DRF delegation pattern  (apply if the source has `serializer_class`)
────────────────────────────────────────
If the class has a `serializer_class = SomeSerializer` attribute with no (or
minimal) method body, the class is a DRF generic view that delegates all logic
to the serializer. You MUST also read the serializer file:

  Call: read_source_file("<file containing SomeSerializer>")

  Focus on:
    • Field definitions  — what the endpoint accepts
    • validate() / validate_<field>()  — validation rules and error paths
    • create() / update()  — DB writes and side effects
    • to_representation()  — what the response looks like

  Incorporate all of this into the documentation; the serializer IS the
  contract and the implementation, not the view.

────────────────────────────────────────
STEP 2 — Map dependencies
────────────────────────────────────────
Call: get_function_dependencies("{target_file}", "{target_function}")

Identify which dependencies are external services, DB writes, signals, or tasks
— these become side effects.

────────────────────────────────────────
STEP 3 — Check for decoupled flows
────────────────────────────────────────
Call: get_decoupled_flows("{target_file}")

If `{target_function}` is framework-invoked (state-machine hook, signal receiver,
Celery task), note this in the summary and behaviours.

────────────────────────────────────────
OUTPUT — documentation block only
────────────────────────────────────────
Output ONLY the following block. No prose, no code, no explanation.

<doc>
{{
  "summary": "2-3 sentences, active voice. What this function does, its role in the system, and the most important behavioral variation. No bullet lists.",
  "side_effects": "Single terse line listing external effects: e.g. 'DB write (GatewayRefund) · signal emitted (create_or_update_log_signal) · Kafka publish'. Use null if there are none.",
  "note": "One sentence for a genuine gotcha or non-obvious constraint. Use null if nothing unusual."
}}
</doc>

Rules:
- summary must be flowing prose, never a bullet list
- side_effects must be a single string (not a list), or null
- note must be null unless genuinely surprising or non-obvious
The JSON must be valid. Base everything strictly on what you read.
"""

    def generate_test_update(
        self,
        target_function: str,
        target_file: str,
        diff_text: str,
        additional_context: str = ""
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Update an existing test for a function that was modified.

        Unlike generate_test(), this prompt is constrained to make the MINIMAL
        change to the existing test file — only touching what the diff requires.

        Args:
            target_function: Name of the modified function
            target_file: File containing the function (relative to project root)
            diff_text: Raw unified diff for this file (for LLM context)
            additional_context: Optional extra context

        Returns:
            (test_code, doc) — complete updated test file + updated doc dict.
        """
        prompt = self._build_test_update_prompt(
            target_function, target_file, diff_text, additional_context
        )
        if self._is_cursor:
            return self._invoke_cursor(prompt)
        result = self.graph.invoke({
            "messages": [HumanMessage(content=prompt)]
        })
        return self._extract_result(result)

    @staticmethod
    def _build_test_update_prompt(
        target_function: str,
        target_file: str,
        diff_text: str,
        additional_context: str,
    ) -> str:
        return f"""You are an expert Python test engineer. The function below was MODIFIED \
and its existing test needs to be updated to match.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Modified function : {target_function}
  Source file       : {target_file}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Here is the diff that was applied to this file:

```diff
{diff_text}
```

────────────────────────────────────────
CRITICAL CONSTRAINT — MINIMAL CHANGES ONLY
────────────────────────────────────────
Your goal is NOT to rewrite the test suite. It is to make the smallest possible
update that keeps the tests correct after the code change above.

  ✓ Add test cases for genuinely NEW behaviour introduced by the diff
  ✓ Fix test cases that now assert the WRONG thing (because the code changed)
  ✗ Do NOT restructure, reformat, or rename existing test functions
  ✗ Do NOT remove test cases for behaviour that still exists
  ✗ Do NOT change imports unless the diff requires it
  ✗ Do NOT alter test cases that are unaffected by the diff

────────────────────────────────────────
STEP 1 — Read the existing test file  (MANDATORY)
────────────────────────────────────────
Call: get_module_test_examples("{target_file}")

This returns the current test file in full. Treat it as the base you are
editing — not a reference to copy style from. Every test case in it must
appear in your output unless it was testing behaviour that was deleted.

────────────────────────────────────────
STEP 2 — Read the updated source file  (MANDATORY)
────────────────────────────────────────
Call: read_source_file("{target_file}")

Read the CURRENT implementation (post-diff). Extract:
  • The exact new signature of `{target_function}`
  • Any new parameters, return values, or exceptions
  • Any new branches introduced by the diff

────────────────────────────────────────
STEP 3 — Map updated dependencies
────────────────────────────────────────
Call: get_function_dependencies("{target_file}", "{target_function}")

Check whether any new external calls were introduced that need mocking.
Only add new mocks — do not touch mocks for dependencies that haven't changed.

────────────────────────────────────────
STEP 4 — Check decoupled flows
────────────────────────────────────────
Call: get_decoupled_flows("{target_file}")

If the function's decorator changed (e.g. a new signal, a different state),
update the test calling convention accordingly.

────────────────────────────────────────
STEP 5 — Output the complete updated test file
────────────────────────────────────────
Output the ENTIRE test file content (not a patch, not just the new cases).
The file must be immediately runnable without manual edits.

{additional_context}

Output the complete updated test file in a ```python block.
Immediately after the closing ```, output an updated behavioural documentation block:

<doc>
{{
  "summary": "One sentence: what this function does and its role in the system",
  "behaviors": ["key observable behavior 1", "behavior 2"],
  "side_effects": ["signals emitted", "tasks enqueued", "DB writes — empty list if none"],
  "test_coverage": "what the generated tests verify"
}}
</doc>

The JSON inside <doc> must be valid. Base it only on what you read in the source.
No other prose outside the code block and the <doc> block.
"""

    def _invoke_cursor(self, prompt: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        One-shot path for CursorAgentLLM.

        cursor agent has its own tool loop and file access, so we embed the
        source file contents directly in the prompt rather than relying on
        LangGraph tool calls, then delegate the full task to the agent.
        """
        # Embed source files referenced in the prompt so cursor agent
        # has full context without needing to call our custom Python tools.
        import re
        file_refs = re.findall(r'(?:read_source_file\("|--file |file:\s*)([^\s"\']+\.py)', prompt)
        context_blocks = []
        seen = set()
        for ref in file_refs:
            if ref in seen:
                continue
            seen.add(ref)
            candidate = self.project_root / ref
            if candidate.exists():
                try:
                    src = candidate.read_text(encoding="utf-8", errors="replace")
                    context_blocks.append(f"### Source: {ref}\n```python\n{src}\n```")
                except OSError:
                    pass

        full_prompt = prompt
        if context_blocks:
            full_prompt = (
                "The following source files are provided for context:\n\n"
                + "\n\n".join(context_blocks)
                + "\n\n---\n\n"
                + prompt
            )

        response = self.llm.invoke([HumanMessage(content=full_prompt)])
        # Wrap in the same result shape _extract_result expects
        fake_result = {"messages": [response]}
        return self._extract_result(fake_result)

    @staticmethod
    def _extract_result(result: Dict) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Extract test code and doc dict from the agent result.

        Returns:
            (test_code, doc) — doc is None if the LLM omitted the <doc> block
            or it contained invalid JSON.
        """
        messages = result.get("messages", [])

        for msg in reversed(messages):
            if not isinstance(msg, AIMessage):
                continue
            content = msg.content

            # --- Check for explicit skip decision ---
            skip_match = re.search(r"<skip>(.*?)</skip>", content, re.DOTALL)
            if skip_match:
                reason = skip_match.group(1).strip()
                return f"__SKIP__:{reason}", None

            # --- Extract test code ---
            test_code = "No test code generated"
            if "```python" in content:
                start = content.find("```python") + 9
                end = content.find("```", start)
                if end != -1:
                    test_code = content[start:end].strip()
            elif content.strip():
                test_code = content.strip()

            # --- Extract <doc> block ---
            doc: Optional[Dict[str, Any]] = None
            doc_match = re.search(r"<doc>\s*(\{.*?\})\s*</doc>", content, re.DOTALL)
            if doc_match:
                try:
                    parsed = json.loads(doc_match.group(1))
                    if isinstance(parsed, dict) and "summary" in parsed:
                        doc = parsed
                except json.JSONDecodeError:
                    pass

            return test_code, doc

        return "No test code generated", None
