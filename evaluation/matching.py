"""
evaluation/matching.py - Matches generated requirements to gold requirements.

Similarity: MiniLM cosine (one worker call) with EVAL_MATCH_THRESHOLD, or word
overlap (Jaccard) with EVAL_LEXICAL_MATCH if embeddings are unavailable.
Greedy one-to-one: the most similar pair first, each requirement used once.
"""

import config
from checks.quality import content_words, jaccard
from context_loader import text_similarities


def similarity_matrix(generated: list[str], gold: list[str]) -> tuple[list[list[float]], str, float]:
    """(matrix[generated][gold], method, threshold)."""
    if not generated or not gold:
        return [[0.0] * len(gold) for _ in generated], "none", 1.0
    try:
        full = text_similarities(generated + gold)
        n = len(generated)
        return [row[n:] for row in full[:n]], "embedding", config.EVAL_MATCH_THRESHOLD
    except Exception:
        gw = [content_words(t) for t in generated]
        dw = [content_words(t) for t in gold]
        return [[jaccard(a, b) for b in dw] for a in gw], "lexical", config.EVAL_LEXICAL_MATCH


def match(generated: list[str], gold: list[str]) -> dict:
    """{"pairs": [(gen_index, gold_index, similarity)], "method", "threshold"}."""
    matrix, method, threshold = similarity_matrix(generated, gold)
    candidates = sorted(((matrix[i][j], i, j) for i in range(len(generated)) for j in range(len(gold))),
                        reverse=True)
    used_gen, used_gold, pairs = set(), set(), []
    for score, i, j in candidates:
        if score < threshold:
            break
        if i in used_gen or j in used_gold:
            continue
        used_gen.add(i)
        used_gold.add(j)
        pairs.append((i, j, round(float(score), 3)))
    return {"pairs": pairs, "method": method, "threshold": threshold}
