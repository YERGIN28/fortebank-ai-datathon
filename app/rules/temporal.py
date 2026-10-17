"""Evidence-point relationships; never invent continuous intervals between frames."""
import math

EPSILON_SECONDS = 0.000001  # Only floating-point PTS roundoff, not an evaluation tolerance.


def _common_points(groups):
    """Keep actual evidence timestamps; do not fill gaps using min/max intervals."""
    if not groups or any(not group for group in groups):
        return []
    return sorted({point for point in groups[0]
                   if all(any(abs(point - other) <= EPSILON_SECONDS for other in group)
                          for group in groups[1:])})


def confirmed_time(rule, checks):
    """Return a supported action timestamp, or None for temporal uncertainty.

    A rule explicitly declares which facts must share a sampled moment and
    which preceding actions must have evidence no later than that moment.
    This does not infer object identity, legal applicability or tracking.
    """
    policy = rule.get('temporal_policy')
    if not isinstance(policy, dict):
        return None
    simultaneous = policy.get('simultaneous', [])
    predecessors = policy.get('after', [])
    anchor = rule.get('time_condition')
    if (not isinstance(simultaneous, list) or not simultaneous
            or not isinstance(predecessors, list) or anchor not in simultaneous):
        return None
    if any(not isinstance(name, str) for name in simultaneous + predecessors):
        return None
    required = set(rule.get('conditions', []) + rule.get('scope_conditions', []))
    if not set(simultaneous + predecessors) <= required:
        return None
    evidence = {}
    for name in set(simultaneous + predecessors):
        check = checks.get(name)
        if not isinstance(check, dict) or check.get('state') != 'observed':
            return None
        times = check.get('evidence_timestamps_sec')
        if (not isinstance(times, list) or not times
                or any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in times)):
            return None
        evidence[name] = sorted(set(times))
    common = _common_points([evidence[name] for name in simultaneous])
    if policy.get('anchor_last', False):
        common = [t for t in common if abs(t - max(evidence[anchor])) <= EPSILON_SECONDS]
    for name in predecessors:
        common = [t for t in common if t + EPSILON_SECONDS >= max(evidence[name])]
    return max(common) if common else None
