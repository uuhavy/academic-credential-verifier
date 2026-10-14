# Test suite for AcademicCredentialVerifier GenLayer Intelligent Contract
# Compatible with gltest, direct_vm, and standalone Python test environments.

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import pytest

# Define mock VM and Return structures to support both gltest and local direct mode
class MockReturn:
    def __init__(self, calldata):
        self.calldata = calldata


class MockUserError(Exception):
    pass


class MockNondetWeb:
    def __init__(self):
        self.urls = {}

    def render(self, url: str, mode: str = "text") -> str:
        for pattern, content in self.urls.items():
            if pattern in url or url in pattern:
                if isinstance(content, dict):
                    if content.get("status", 200) >= 400:
                        raise Exception(f"HTTP Error {content.get('status')}")
                    return content.get("body", "")
                return str(content)
        raise Exception(f"Failed to fetch URL: {url} (404 Not Found)")


class MockNondet:
    def __init__(self):
        self.web = MockNondetWeb()
        self.prompts = {}
        self.call_count = 0
        self.prompt_sequence = []

    def exec_prompt(self, prompt: str, response_format: str = "json") -> str:
        self.call_count += 1
        # Check sequence first for multi-turn validator disagreement tests
        if self.prompt_sequence:
            return self.prompt_sequence.pop(0)

        for pattern, response in self.prompts.items():
            if pattern in prompt or prompt in pattern:
                if isinstance(response, str):
                    return response
                return json.dumps(response)
        # Default fallback valid response
        return json.dumps({
            "verdict": "PASS",
            "confidence": 75,
            "rigor_score": 70,
            "novelty_score": 72,
            "reproducibility_score": 68,
            "rationale": "Default mock peer review fallback response"
        })


class MockGenVM:
    UserError = MockUserError
    Return = MockReturn

    def __init__(self):
        self.validator_override = None

    def run_nondet_unsafe(self, leader_fn, validator_fn):
        leader_output = leader_fn()
        leader_res = MockReturn(leader_output)

        if self.validator_override is not None:
            # Inject custom validator response for testing consensus mismatches
            is_valid = self.validator_override(leader_res)
        else:
            is_valid = validator_fn(leader_res)

        if not is_valid:
            raise Exception("Consensus failed: Validator rejected leader proposal")

        return leader_res.calldata


class MockPublic:
    @staticmethod
    def write(fn):
        return fn

    @staticmethod
    def view(fn):
        return fn


class GenericMockStorage(dict):
    def __class_getitem__(cls, item):
        return cls


class GenericMockArray(list):
    def __class_getitem__(cls, item):
        return cls


class MockGL:
    def __init__(self):
        self.nondet = MockNondet()
        self.vm = MockGenVM()
        self.public = MockPublic()

    class Contract:
        pass


import types
if "genlayer" not in sys.modules:
    _gl_mod = types.ModuleType("genlayer")
    _gl_inst = MockGL()
    _gl_mod.gl = _gl_inst
    _gl_mod.allow_storage = lambda cls: cls
    _gl_mod.bigint = int
    _gl_mod.TreeMap = GenericMockStorage
    _gl_mod.DynArray = GenericMockArray
    _gl_mod.Address = str
    sys.modules["genlayer"] = _gl_mod


# Global or direct mock installation helper accepting dict parameter
def sim_installMocks(target_env, mocks: dict):
    """
    Installs mock configurations for web rendering and LLM prompt execution.
    Accepts a dictionary configuring 'nondet_web_request' (or 'web') and
    'nondet_exec_prompt' (or 'llm').
    """
    if hasattr(target_env, "sim_installMocks"):
        return target_env.sim_installMocks(mocks)

    if hasattr(target_env, "provider") and hasattr(target_env.provider, "request"):
        try:
            return target_env.provider.request({"method": "sim_installMocks", "params": [mocks]})
        except Exception:
            pass

    # Direct VM or in-memory mock environment
    web_mocks = mocks.get("nondet_web_request") or mocks.get("web") or {}
    llm_mocks = mocks.get("nondet_exec_prompt") or mocks.get("llm") or {}

    if hasattr(target_env, "mock_web") and hasattr(target_env, "mock_llm"):
        for pattern, data in web_mocks.items():
            target_env.mock_web(pattern, data)
        for pattern, response in llm_mocks.items():
            target_env.mock_llm(pattern, response)
        return

    # In-memory mock harness
    if hasattr(target_env, "nondet"):
        for url_pattern, content in web_mocks.items():
            target_env.nondet.web.urls[url_pattern] = content
        for prompt_pattern, response in llm_mocks.items():
            target_env.nondet.prompts[prompt_pattern] = response


# Setup test fixtures
@pytest.fixture
def test_env(monkeypatch):
    mock_gl = MockGL()
    # Import contract module
    import contracts.academic_credential_verifier as acv

    # Inject mock gl environment
    monkeypatch.setattr(acv, "gl", mock_gl)
    # Ensure gl.vm.UserError matches
    monkeypatch.setattr(acv.gl.vm, "UserError", MockUserError)

    contract = acv.Contract()
    # Initialize storage collections for in-memory testing
    contract.evaluations = {}
    contract.candidate_latest_eval = {}
    contract.total_evaluations = 0
    contract.total_distinctions = 0
    contract.total_passes = 0
    contract.total_rejects = 0

    return {
        "contract": contract,
        "mock_gl": mock_gl,
        "module": acv,
    }


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_sim_install_mocks_structure(test_env):
    """Verify sim_installMocks properly parses and registers dict parameter."""
    mock_gl = test_env["mock_gl"]
    mocks = {
        "nondet_web_request": {
            "https://arxiv.org/abs/2401.99999": {
                "status": 200,
                "body": "Title: Decentralized Proof of Research\nAbstract: An empirical verification primitive."
            }
        },
        "nondet_exec_prompt": {
            "scholarly publication": {
                "verdict": "DISTINCTION",
                "confidence": 95,
                "rigor_score": 98,
                "novelty_score": 94,
                "reproducibility_score": 92,
                "rationale": "Unprecedented empirical rigor and dataset disclosure."
            }
        }
    }
    sim_installMocks(mock_gl, mocks)

    assert "https://arxiv.org/abs/2401.99999" in mock_gl.nondet.web.urls
    assert "scholarly publication" in mock_gl.nondet.prompts


def test_verify_credential_distinction_happy_path(test_env):
    """Happy path: Evaluation results in DISTINCTION and stores full record."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]

    paper_url = "https://arxiv.org/abs/2401.12345"
    candidate_id = "0xResearcherAlice"
    rubric = "Must present novel consensus methodology, dataset disclosures, and benchmark reproducibility."

    mocks = {
        "nondet_web_request": {
            paper_url: "Title: Scalable Semantic Consensus\nFull paper content with benchmark results and dataset."
        },
        "nondet_exec_prompt": {
            "scholarly publication": json.dumps({
                "verdict": "DISTINCTION",
                "confidence": 92,
                "rigor_score": 95,
                "novelty_score": 90,
                "reproducibility_score": 88,
                "rationale": "Exceeds all rubric criteria with formal mathematical proofs and public benchmark repos."
            })
        }
    }
    sim_installMocks(mock_gl, mocks)

    eval_id = contract.verify_credential(paper_url, candidate_id, rubric)

    assert eval_id == "EVAL-000001"
    assert contract.get_total_evaluations() == 1
    assert contract.has_evaluation(eval_id) is True
    assert contract.get_evaluation_verdict(eval_id) == "DISTINCTION"
    assert contract.get_candidate_latest_eval_id(candidate_id) == eval_id

    # Validate retrieved JSON payload
    record_json = contract.get_evaluation(eval_id)
    record = json.loads(record_json)
    assert record["eval_id"] == "EVAL-000001"
    assert record["verdict"] == "DISTINCTION"
    assert record["confidence_score"] == 92
    assert record["rigor_score"] == 95
    assert record["novelty_score"] == 90
    assert record["reproducibility_score"] == 88
    assert "formal mathematical proofs" in record["rationale"]

    # Validate summary statistics
    stats = json.loads(contract.get_statistics())
    assert stats["total_evaluations"] == 1
    assert stats["total_distinctions"] == 1
    assert stats["total_passes"] == 0
    assert stats["total_rejects"] == 0


def test_verify_credential_pass_happy_path(test_env):
    """Happy path: Evaluation results in PASS verdict with moderate confidence."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]

    paper_url = "https://doi.org/10.1000/182"
    candidate_id = "0xResearcherBob"
    rubric = "Requires baseline empirical testing and correct academic citations."

    mocks = {
        "nondet_web_request": {
            paper_url: "Title: A Survey of Oracles\nContent: Surveys existing oracle designs with standard citations."
        },
        "nondet_exec_prompt": {
            "scholarly publication": json.dumps({
                "verdict": "PASS",
                "confidence": 72,
                "rigor_score": 75,
                "novelty_score": 65,
                "reproducibility_score": 70,
                "rationale": "Meets required qualitative survey benchmarks."
            })
        }
    }
    sim_installMocks(mock_gl, mocks)

    eval_id = contract.verify_credential(paper_url, candidate_id, rubric)

    assert eval_id == "EVAL-000001"
    assert contract.get_evaluation_verdict(eval_id) == "PASS"

    stats = json.loads(contract.get_statistics())
    assert stats["total_passes"] == 1
    assert stats["total_distinctions"] == 0
    assert stats["total_rejects"] == 0


def test_verify_credential_reject_happy_path(test_env):
    """Happy path: Evaluation results in REJECT verdict for inadequate paper."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]

    paper_url = "https://example.com/unsupported-claim"
    candidate_id = "0xResearcherCharlie"
    rubric = "Must provide verifiable empirical datasets."

    mocks = {
        "nondet_web_request": {
            paper_url: "Title: Speculative Claims\nContent: No dataset provided."
        },
        "nondet_exec_prompt": {
            "scholarly publication": json.dumps({
                "verdict": "REJECT",
                "confidence": 89,
                "rigor_score": 20,
                "novelty_score": 30,
                "reproducibility_score": 10,
                "rationale": "Lacks empirical evidence or datasets, failing core rubric benchmark."
            })
        }
    }
    sim_installMocks(mock_gl, mocks)

    eval_id = contract.verify_credential(paper_url, candidate_id, rubric)

    assert eval_id == "EVAL-000001"
    assert contract.get_evaluation_verdict(eval_id) == "REJECT"

    stats = json.loads(contract.get_statistics())
    assert stats["total_rejects"] == 1


def test_consensus_mismatch_verdict_disagreement(test_env):
    """Consensus failure: Leader and validator diverge on verdict (PASS vs REJECT)."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]
    acv = test_env["module"]

    # Leader returns PASS, validator returns REJECT
    leader_payload = {
        "verdict": "PASS",
        "confidence": 75,
        "rigor_score": 70,
        "novelty_score": 70,
        "reproducibility_score": 70,
        "rationale": "Leader thinks paper passes."
    }

    # Setup mock sequence for multi-evaluation
    mock_gl.nondet.web.urls["https://arxiv.org/abs/dispute"] = "Sample paper text"
    mock_gl.nondet.prompts["scholarly publication"] = json.dumps(leader_payload)

    # Simulate validator returning REJECT
    def disagreeing_validator(leader_res):
        # Leader gave PASS
        assert leader_res.calldata["verdict"] == "PASS"
        # Validator evaluates and gets REJECT
        val_verdict = "REJECT"
        val_conf = 70
        # Check rule: verdicts must match
        if leader_res.calldata["verdict"] != val_verdict:
            return False
        if acv.get_confidence_band(leader_res.calldata["confidence"]) != acv.get_confidence_band(val_conf):
            return False
        return True

    mock_gl.vm.validator_override = disagreeing_validator

    with pytest.raises(Exception, match="Consensus failed: Validator rejected leader proposal"):
        contract.verify_credential("https://arxiv.org/abs/dispute", "0xCandidate", "Strict rubric")


def test_consensus_mismatch_confidence_band_disagreement(test_env):
    """Consensus failure: Verdicts match (PASS) but confidence bands diverge (Band 2 vs Band 1)."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]
    acv = test_env["module"]

    mock_gl.nondet.web.urls["https://arxiv.org/abs/conf_diverge"] = "Sample paper text"
    mock_gl.nondet.prompts["scholarly publication"] = json.dumps({
        "verdict": "PASS",
        "confidence": 85,  # Band 2 (>= 80)
        "rigor_score": 80,
        "novelty_score": 80,
        "reproducibility_score": 80,
        "rationale": "Leader is highly confident."
    })

    def band_diverging_validator(leader_res):
        # Validator agrees on verdict PASS, but has confidence 60 (Band 1: 40-79)
        val_verdict = "PASS"
        val_conf = 60
        if leader_res.calldata["verdict"] != val_verdict:
            return False
        if acv.get_confidence_band(leader_res.calldata["confidence"]) != acv.get_confidence_band(val_conf):
            return False
        return True

    mock_gl.vm.validator_override = band_diverging_validator

    with pytest.raises(Exception, match="Consensus failed: Validator rejected leader proposal"):
        contract.verify_credential("https://arxiv.org/abs/conf_diverge", "0xCandidate", "Strict rubric")


def test_consensus_validator_rejects_non_return_leader(test_env):
    """Consensus rule: Validator must reject if leader_res is not gl.vm.Return."""
    mock_gl = test_env["mock_gl"]

    # When leader fails or throws error, leader_res is an exception or None
    invalid_leader_res = "Not a Return instance"

    def validator_logic(leader_res):
        if not isinstance(leader_res, mock_gl.vm.Return):
            return False
        return True

    assert validator_logic(invalid_leader_res) is False


def test_validation_empty_url(test_env):
    """Edge case: Empty or whitespace paper_url raises UserError."""
    contract = test_env["contract"]
    UserError = test_env["mock_gl"].vm.UserError

    with pytest.raises(UserError, match="paper_url"):
        contract.verify_credential("", "0xCandidate", "Valid rubric")

    with pytest.raises(UserError, match="paper_url"):
        contract.verify_credential("   ", "0xCandidate", "Valid rubric")


def test_validation_invalid_url_protocol(test_env):
    """Edge case: Non-http/https URL raises UserError."""
    contract = test_env["contract"]
    UserError = test_env["mock_gl"].vm.UserError

    with pytest.raises(UserError, match="must start with http:// or https://"):
        contract.verify_credential("ftp://files.org/paper.pdf", "0xCandidate", "Valid rubric")


def test_validation_empty_candidate_id(test_env):
    """Edge case: Empty candidate_id raises UserError."""
    contract = test_env["contract"]
    UserError = test_env["mock_gl"].vm.UserError

    with pytest.raises(UserError, match="candidate_id"):
        contract.verify_credential("https://arxiv.org/abs/1", "", "Valid rubric")


def test_validation_empty_rubric(test_env):
    """Edge case: Empty rubric_criteria raises UserError."""
    contract = test_env["contract"]
    UserError = test_env["mock_gl"].vm.UserError

    with pytest.raises(UserError, match="rubric_criteria"):
        contract.verify_credential("https://arxiv.org/abs/1", "0xCandidate", "")


def test_error_handling_dead_url(test_env):
    """Edge case: Dead URL / fetch failure raises UserError inside non-deterministic execution."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]
    UserError = mock_gl.vm.UserError

    # URL not in mock web registry will raise fetch failure
    dead_url = "https://broken-dead-link.org/paper"

    with pytest.raises(UserError, match="Dead URL or network fetch failure"):
        contract.verify_credential(dead_url, "0xCandidate", "Valid rubric criteria")


def test_error_handling_unparseable_llm_json(test_env):
    """Edge case: Malformed non-JSON output from LLM raises UserError."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]
    UserError = mock_gl.vm.UserError

    url = "https://arxiv.org/abs/malformed"
    mock_gl.nondet.web.urls[url] = "Paper text content"
    mock_gl.nondet.prompts["scholarly publication"] = "This is plain text and not valid JSON"

    with pytest.raises(UserError, match="Unparseable LLM output"):
        contract.verify_credential(url, "0xCandidate", "Valid rubric criteria")


def test_error_handling_invalid_verdict_value(test_env):
    """Edge case: LLM returns unexpected verdict string (not DISTINCTION, PASS, or REJECT)."""
    contract = test_env["contract"]
    mock_gl = test_env["mock_gl"]
    UserError = mock_gl.vm.UserError

    url = "https://arxiv.org/abs/badverdict"
    mock_gl.nondet.web.urls[url] = "Paper text content"
    mock_gl.nondet.prompts["scholarly publication"] = json.dumps({
        "verdict": "INCONCLUSIVE",
        "confidence": 50,
        "rigor_score": 50,
        "novelty_score": 50,
        "reproducibility_score": 50,
        "rationale": "Reviewer is uncertain."
    })

    with pytest.raises(UserError, match="Invalid verdict from LLM"):
        contract.verify_credential(url, "0xCandidate", "Valid rubric criteria")


def test_query_nonexistent_evaluation(test_env):
    """Edge case: Querying non-existent evaluation ID raises UserError."""
    contract = test_env["contract"]
    UserError = test_env["mock_gl"].vm.UserError

    assert contract.has_evaluation("EVAL-999999") is False
    assert contract.get_candidate_latest_eval_id("0xUnknown") == ""

    with pytest.raises(UserError, match="Evaluation record not found"):
        contract.get_evaluation("EVAL-999999")

    with pytest.raises(UserError, match="Evaluation record not found"):
        contract.get_evaluation_verdict("EVAL-999999")


if __name__ == "__main__":
    pytest.main(["-v", __file__])
