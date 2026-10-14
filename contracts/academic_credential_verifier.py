# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
import json


@allow_storage
@dataclass
class AcademicEvaluation:
    eval_id: str
    paper_url: str
    candidate_id: str
    rubric_criteria: str
    verdict: str
    confidence_score: bigint
    rigor_score: bigint
    novelty_score: bigint
    reproducibility_score: bigint
    rationale: str
    evaluation_index: bigint


def get_confidence_band(score: int) -> int:
    if score < 40:
        return 0
    elif score < 80:
        return 1
    return 2


class Contract(gl.Contract):
    evaluations: TreeMap[str, AcademicEvaluation]
    candidate_latest_eval: TreeMap[str, str]
    total_evaluations: bigint
    total_distinctions: bigint
    total_passes: bigint
    total_rejects: bigint

    def __init__(self):
        self.total_evaluations = bigint(0)
        self.total_distinctions = bigint(0)
        self.total_passes = bigint(0)
        self.total_rejects = bigint(0)

    @gl.public.write
    def verify_credential(
        self, paper_url: str, candidate_id: str, rubric_criteria: str
    ) -> str:
        if not paper_url or not isinstance(paper_url, str):
            raise gl.vm.UserError("Invalid input: paper_url must be a non-empty string")
        clean_url = paper_url.strip()
        if len(clean_url) == 0:
            raise gl.vm.UserError("Invalid input: paper_url cannot be empty")
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise gl.vm.UserError("Invalid input: paper_url must start with http:// or https://")

        if not candidate_id or not isinstance(candidate_id, str):
            raise gl.vm.UserError("Invalid input: candidate_id must be a non-empty string")
        clean_candidate = candidate_id.strip()
        if len(clean_candidate) == 0:
            raise gl.vm.UserError("Invalid input: candidate_id cannot be empty")

        if not rubric_criteria or not isinstance(rubric_criteria, str):
            raise gl.vm.UserError("Invalid input: rubric_criteria must be a non-empty string")
        clean_rubric = rubric_criteria.strip()
        if len(clean_rubric) == 0:
            raise gl.vm.UserError("Invalid input: rubric_criteria cannot be empty")

        target_url = clean_url
        target_candidate = clean_candidate
        target_rubric = clean_rubric

        def leader_fn() -> dict:
            try:
                raw_text = gl.nondet.web.render(target_url, mode="text")
            except Exception as exc:
                raise gl.vm.UserError(
                    f"Dead URL or network fetch failure: {str(exc)}"
                )

            if not raw_text or len(raw_text.strip()) == 0:
                raise gl.vm.UserError("Paper URL returned empty content")

            clean_sample = raw_text.encode("ascii", errors="ignore").decode("ascii")[:7000]

            prompt_text = (
                "You are an impartial academic review board evaluating a scholarly publication.\n\n"
                f"Candidate ID: {target_candidate}\n"
                f"Evaluation Rubric: {target_rubric}\n\n"
                f"Paper Content (first 7000 chars):\n{clean_sample}\n\n"
                "Evaluate the paper rigorously against the rubric criteria.\n"
                "You must return ONLY a single valid JSON object with the following schema:\n"
                "{\n"
                '  "verdict": "DISTINCTION" | "PASS" | "REJECT",\n'
                '  "confidence": <integer 0-100>,\n'
                '  "rigor_score": <integer 0-100>,\n'
                '  "novelty_score": <integer 0-100>,\n'
                '  "reproducibility_score": <integer 0-100>,\n'
                '  "rationale": "<concise academic evaluation justification>"\n'
                "}\n\n"
                "Verdict definitions:\n"
                "- DISTINCTION: Exceeds rubric requirements with exceptional methodological rigor and novelty.\n"
                "- PASS: Meets essential qualitative benchmarks and core academic requirements.\n"
                "- REJECT: Fails critical rubric requirements, lacks evidence, or contains fatal flaws.\n"
                "Ensure all scores are integers between 0 and 100. Return valid JSON only with no commentary."
            )

            try:
                llm_res = gl.nondet.exec_prompt(
                    prompt_text, response_format="json"
                )
            except Exception as exc:
                raise gl.vm.UserError(f"LLM execution error: {str(exc)}")

            try:
                if isinstance(llm_res, dict):
                    data = llm_res
                else:
                    data = json.loads(llm_res)
            except Exception:
                raise gl.vm.UserError("Unparseable LLM output: response is not valid JSON")

            if not isinstance(data, dict):
                raise gl.vm.UserError("Unparseable LLM output: root element must be a dictionary")

            verdict_val = str(data.get("verdict", "")).strip().upper()
            if verdict_val not in ("DISTINCTION", "PASS", "REJECT"):
                raise gl.vm.UserError(
                    f"Invalid verdict from LLM: '{verdict_val}'. Expected DISTINCTION, PASS, or REJECT"
                )

            def extract_score(key: str, default_val: int = 50) -> int:
                val = data.get(key, default_val)
                try:
                    num = int(val)
                    if num < 0:
                        return 0
                    if num > 100:
                        return 100
                    return num
                except (ValueError, TypeError):
                    return default_val

            confidence_val = extract_score("confidence", 50)
            rigor_val = extract_score("rigor_score", 50)
            novelty_val = extract_score("novelty_score", 50)
            reproducibility_val = extract_score("reproducibility_score", 50)

            raw_rationale = str(data.get("rationale", "No rationale provided"))
            rationale_val = raw_rationale.encode("ascii", errors="ignore").decode("ascii")[:1000]

            return {
                "verdict": verdict_val,
                "confidence": confidence_val,
                "rigor_score": rigor_val,
                "novelty_score": novelty_val,
                "reproducibility_score": reproducibility_val,
                "rationale": rationale_val,
            }

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False

            leader_data = leader_res.calldata
            if not isinstance(leader_data, dict):
                return False

            leader_verdict = leader_data.get("verdict")
            leader_conf = leader_data.get("confidence")
            if leader_verdict not in ("DISTINCTION", "PASS", "REJECT"):
                return False
            if not isinstance(leader_conf, int):
                return False

            try:
                validator_data = leader_fn()
            except Exception:
                return False

            if not isinstance(validator_data, dict):
                return False

            validator_verdict = validator_data.get("verdict")
            validator_conf = validator_data.get("confidence")
            if validator_verdict not in ("DISTINCTION", "PASS", "REJECT"):
                return False
            if not isinstance(validator_conf, int):
                return False

            if leader_verdict != validator_verdict:
                return False

            if get_confidence_band(leader_conf) != get_confidence_band(validator_conf):
                return False

            return True

        adjudication = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        next_index = int(self.total_evaluations) + 1
        eval_id = f"EVAL-{next_index:06d}"
        v_str = str(adjudication["verdict"])

        eval_rec = AcademicEvaluation(
            eval_id=eval_id,
            paper_url=target_url,
            candidate_id=target_candidate,
            rubric_criteria=target_rubric,
            verdict=v_str,
            confidence_score=bigint(adjudication["confidence"]),
            rigor_score=bigint(adjudication["rigor_score"]),
            novelty_score=bigint(adjudication["novelty_score"]),
            reproducibility_score=bigint(adjudication["reproducibility_score"]),
            rationale=str(adjudication["rationale"]),
            evaluation_index=bigint(next_index),
        )

        self.evaluations[eval_id] = eval_rec
        self.candidate_latest_eval[target_candidate] = eval_id
        self.total_evaluations = bigint(next_index)

        if v_str == "DISTINCTION":
            self.total_distinctions = bigint(int(self.total_distinctions) + 1)
        elif v_str == "PASS":
            self.total_passes = bigint(int(self.total_passes) + 1)
        elif v_str == "REJECT":
            self.total_rejects = bigint(int(self.total_rejects) + 1)

        return eval_id

    @gl.public.view
    def get_evaluation(self, eval_id: str) -> str:
        if eval_id not in self.evaluations:
            raise gl.vm.UserError(f"Evaluation record not found for id: {eval_id}")
        rec = self.evaluations[eval_id]
        payload = {
            "eval_id": rec.eval_id,
            "paper_url": rec.paper_url,
            "candidate_id": rec.candidate_id,
            "rubric_criteria": rec.rubric_criteria,
            "verdict": rec.verdict,
            "confidence_score": int(rec.confidence_score),
            "rigor_score": int(rec.rigor_score),
            "novelty_score": int(rec.novelty_score),
            "reproducibility_score": int(rec.reproducibility_score),
            "rationale": rec.rationale,
            "evaluation_index": int(rec.evaluation_index),
        }
        return json.dumps(payload)

    @gl.public.view
    def get_total_evaluations(self) -> int:
        return int(self.total_evaluations)

    @gl.public.view
    def get_evaluation_verdict(self, eval_id: str) -> str:
        if eval_id not in self.evaluations:
            raise gl.vm.UserError(f"Evaluation record not found for id: {eval_id}")
        return self.evaluations[eval_id].verdict

    @gl.public.view
    def has_evaluation(self, eval_id: str) -> bool:
        return eval_id in self.evaluations

    @gl.public.view
    def get_candidate_latest_eval_id(self, candidate_id: str) -> str:
        if candidate_id not in self.candidate_latest_eval:
            return ""
        return self.candidate_latest_eval[candidate_id]

    @gl.public.view
    def get_statistics(self) -> str:
        payload = {
            "total_evaluations": int(self.total_evaluations),
            "total_distinctions": int(self.total_distinctions),
            "total_passes": int(self.total_passes),
            "total_rejects": int(self.total_rejects),
        }
        return json.dumps(payload)
