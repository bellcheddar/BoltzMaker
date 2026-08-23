"""The template renderer: plain, correct, and never wrong.

Not a stub, and not a degraded mode to apologise for. It is what runs on every Mac
without Apple Intelligence, on every non-Apple machine, whenever the binary is
missing, whenever narration times out, and whenever the numeric-integrity gate
rejects what the model produced. That is most of the world most of the time, so it
has to be good enough to ship on its own.

It cannot state a number the FactBlock did not supply, because it only ever
interpolates. What it gives up is fluency: it will not notice that a poorly placed
ligand and a wide potency spread are the same story told twice.
"""

from __future__ import annotations

from jinja2 import Environment

from .factblock import FactBlock

_ENV = Environment(trim_blocks=True, lstrip_blocks=True, autoescape=False)

#: British English, and deliberately flat. Every value comes from the block already
#: formatted, so this template does no rounding, no unit handling and no judgement.
_TARGET = _ENV.from_string("""\
{{ b.display_name }} is {{ b.receptor }}{% if b.partners != 'none' %} co-folded with \
{{ b.partners }}{% endif %}.

The structure is {{ b.confidence.interpretation }} \
(confidence {{ b.confidence.confidence_score }}, ipTM {{ b.confidence.iptm }}, \
ligand ipTM {{ b.confidence.ligand_iptm }}).
{% if b.ligands %}
{% for l in b.ligands %}
{{ l.name }} ({{ l.ligand_class }}{% if l.role != 'not specified' %}, {{ l.role }}\
{% endif %}) was run against {{ l.pocket }}: predicted pIC50 {{ l.predicted_pic50 }} \
(spread {{ l.pic50_spread }}), binder probability {{ l.binder_probability }}, \
ranked {{ l.rank }}. Interactions: {{ l.contacts_summary }}.
{% endfor %}
{% else %}
No ligand was present; this is a ligand-free control.
{% endif %}
{% if b.ligands_omitted %}
{{ b.ligands_omitted }} further ligand(s) are not described here.
{% endif %}
{% if b.pose %}
Against {{ b.pose.reference }} the prediction {{ b.pose.verdict }} \
(pose {{ b.pose.pose_rmsd }}, site {{ b.pose.site_rmsd }}).
{% endif %}
{% if b.sse %}
Secondary structure: {{ b.sse.motif_count }} compared, {{ b.sse.largest_shift }}.
{% endif %}
{% if b.flags %}
Flagged: {% for f in b.flags %}{{ f }}{% if not loop.last %}; {% endif %}{% endfor %}.
{% else %}
Nothing was flagged.
{% endif %}
Recommendation: {{ b.recommendation }}.
""")


def render(block: FactBlock) -> str:
    return _TARGET.render(b=block).strip()


def render_summary(block: FactBlock) -> dict:
    """The same shape the Swift narrator returns, so callers need not branch.

    A campaign whose summaries are half model-written and half template-written must
    still be one list of the same thing; `generatedBy` is how a reader tells which is
    which, not the shape of the object.
    """
    notes = [
        f"{l.name} ({l.ligand_class}) at {l.pocket}: predicted pIC50 "
        f"{l.predicted_pic50}, binder probability {l.binder_probability}, "
        f"ranked {l.rank}. Interactions: {l.contacts_summary}."
        for l in block.ligands
    ]
    if block.pose:
        notes.append(f"Against {block.pose.reference} the prediction "
                     f"{block.pose.verdict} (pose {block.pose.pose_rmsd}).")
    return {
        "confidence": (f"The structure is {block.confidence.interpretation}: confidence "
                       f"{block.confidence.confidence_score}, ipTM "
                       f"{block.confidence.iptm}, ligand ipTM "
                       f"{block.confidence.ligand_iptm}."),
        "ligandNotes": notes,
        "recommendation": block.recommendation,
        "caveat": ("; ".join(block.flags) + "." if block.flags
                   else "Nothing was flagged for this target."),
    }


_CAMPAIGN = _ENV.from_string("""\
{{ s.campaign_name }}

{% for label, value in s.rows %}
{{ label }}: {{ value }}
{% endfor %}
{% if s.top_by_potency %}

Highest predicted potency:
{% for t in s.top_by_potency %}
  - {{ t }}
{% endfor %}
{% endif %}
""")


def render_campaign(stats) -> str:
    """The campaign overview without a model. Same guarantee as the per-target one."""
    return _CAMPAIGN.render(s=stats).strip()
