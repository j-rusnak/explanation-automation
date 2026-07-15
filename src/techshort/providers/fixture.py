from __future__ import annotations

from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    Claim,
    ClaimsManifest,
    EvidenceManifest,
    EvidenceSpan,
    Scene,
    ScriptManifest,
    ScriptSegment,
    StoryboardManifest,
    VisualSpec,
)


class FixtureProvider:
    """Deterministic provider for the original rolling-shutter fixture."""

    phrases = [
        "A rolling-shutter sensor does not expose every image row at the same instant.",
        "If an object or camera moves during that interval, each row records a slightly different moment.",
        "Faster motion or a longer frame readout increases the visible skew.",
        "A global shutter exposes all rows together and therefore avoids this row-timing skew.",
        "A faster readout reduces distortion, but it does not guarantee a perfectly undistorted image.",
    ]

    def evidence(self, source_text: str, source_id: str, source_hash: str) -> EvidenceManifest:
        spans: list[EvidenceSpan] = []
        for index, phrase in enumerate(self.phrases, 1):
            start = source_text.find(phrase)
            if start < 0:
                raise ValueError(f"fixture evidence phrase {index} is missing from source")
            end = start + len(phrase)
            spans.append(
                EvidenceSpan(
                    evidence_id=f"evidence-{index:02d}",
                    source_id=source_id,
                    section_heading="Rolling shutter and motion",
                    char_start=start,
                    char_end=end,
                    excerpt=phrase,
                    context=source_text[max(0, start - 80) : min(len(source_text), end + 80)],
                    source_hash=source_hash,
                    extraction_confidence=1.0,
                    locator=f"techshort://source/{source_id}?start={start}&end={end}",
                )
            )
        return EvidenceManifest(
            version_id=f"evidence-{stable_hash([s.excerpt for s in spans])[:12]}", evidence=spans
        )

    def generate_claims(self, source_text: str, source_id: str, source_hash: str) -> ClaimsManifest:
        evidence = self.evidence(source_text, source_id, source_hash)
        claims = [
            Claim(
                claim_id="claim-row-timing",
                text=self.phrases[0],
                evidence_span_ids=["evidence-01"],
                relationship="direct",
                evidence_label="documented",
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-motion-skew",
                text=self.phrases[1],
                evidence_span_ids=["evidence-02"],
                relationship="direct",
                evidence_label="documented",
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-parameters",
                text=self.phrases[2],
                evidence_span_ids=["evidence-03"],
                relationship="direct",
                evidence_label="documented",
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-global",
                text=self.phrases[3],
                evidence_span_ids=["evidence-04"],
                relationship="direct",
                evidence_label="documented",
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-limitation",
                text=self.phrases[4],
                evidence_span_ids=["evidence-05"],
                relationship="direct",
                evidence_label="documented",
                limitation="Other motion blur, lens effects, and processing can still alter the image.",
                confidence=1.0,
            ),
        ]
        return ClaimsManifest(
            version_id=f"claims-{stable_hash(claims)[:12]}",
            evidence_version_id=evidence.version_id,
            claims=claims,
        )

    def generate_angles(self) -> list[str]:
        return ["surprising-result", "everyday-mechanism", "engineering-tradeoff"]

    def generate_script(self, claims: ClaimsManifest, angle: str) -> ScriptManifest:
        segments = [
            ScriptSegment(
                segment_id="segment-01",
                text="Why can a straight propeller look bent in a phone video? The shape did not suddenly change.",
                segment_type="hook",
                claim_ids=["claim-motion-skew"],
                approximate_duration=7,
            ),
            ScriptSegment(
                segment_id="segment-02",
                text="Many camera sensors use a rolling shutter: they record the image row by row, so the top and bottom are captured at slightly different moments.",
                segment_type="factual",
                claim_ids=["claim-row-timing"],
                approximate_duration=10,
            ),
            ScriptSegment(
                segment_id="segment-03",
                text="When the camera or subject moves during that readout, each row sees a different position. Stack those rows, and a vertical edge can lean or wobble.",
                segment_type="factual",
                claim_ids=["claim-motion-skew"],
                approximate_duration=11,
            ),
            ScriptSegment(
                segment_id="segment-04",
                text="Think of scanning a page while the paper slides sideways: the scan is faithful at each instant, but the combined page is skewed.",
                segment_type="analogy",
                claim_ids=["claim-motion-skew"],
                approximate_duration=10,
            ),
            ScriptSegment(
                segment_id="segment-05",
                text="The effect grows with faster motion or a longer frame readout. A shorter readout reduces the offset between rows.",
                segment_type="factual",
                claim_ids=["claim-parameters"],
                approximate_duration=9,
            ),
            ScriptSegment(
                segment_id="segment-06",
                text="A global shutter captures all rows together, avoiding this particular row-timing distortion.",
                segment_type="factual",
                claim_ids=["claim-global"],
                approximate_duration=7,
            ),
            ScriptSegment(
                segment_id="segment-07",
                text="But faster readout is not a promise of a perfect image: motion blur, lens effects, and image processing can still change what you see.",
                segment_type="limitation",
                claim_ids=["claim-limitation"],
                approximate_duration=9,
            ),
            ScriptSegment(
                segment_id="segment-08",
                text="So the bent propeller is best read as a timing map, not a bent object.",
                segment_type="cta",
                claim_ids=[],
                approximate_duration=6,
            ),
        ]
        return ScriptManifest(
            version_id=f"script-{stable_hash(segments)[:12]}",
            claims_version_id=claims.version_id,
            angle=angle,
            segments=segments,
        )

    def generate_storyboard(self, script: ScriptManifest) -> StoryboardManifest:
        primitives = [
            "KineticText",
            "SourceReceipt",
            "MechanismDiagram",
            "Comparison",
            "ChartReveal",
            "ParameterSimulation",
            "LimitationCard",
            "KineticText",
        ]
        titles = [
            "Why does it bend?",
            "Rows capture different moments",
            "Motion becomes skew",
            "Scan while sliding",
            "More time, more skew",
            "Global vs rolling",
            "Important limitation",
            "A timing map",
        ]
        claim_map = [
            ["claim-motion-skew"],
            ["claim-row-timing"],
            ["claim-motion-skew"],
            ["claim-motion-skew"],
            ["claim-parameters"],
            ["claim-global"],
            ["claim-limitation"],
            [],
        ]
        scenes: list[Scene] = []
        time = 0.0
        for index, segment in enumerate(script.segments):
            duration = segment.approximate_duration
            visual = VisualSpec(
                title=titles[index],
                body=segment.text,
                citation=claim_map[index][0] if claim_map[index] else None,
            )
            if primitives[index] == "MechanismDiagram":
                visual = VisualSpec(
                    title=titles[index],
                    body="Rows sample a moving edge at successive moments",
                    nodes=[
                        {"id": "sensor", "label": "sensor rows", "x": 0.2, "y": 0.45},
                        {
                            "id": "object",
                            "label": "moving edge",
                            "x": 0.78,
                            "y": 0.45,
                            "state": "active",
                        },
                    ],
                    edges=[{"source": "sensor", "target": "object", "label": "time"}],
                    citation="claim-motion-skew",
                )
            elif primitives[index] == "ChartReveal":
                visual = VisualSpec(
                    title=titles[index],
                    series=[0, 10, 20, 30, 40],
                    labels=["0", "5", "10", "15", "20 ms"],
                    citation="claim-parameters",
                )
            elif primitives[index] == "ParameterSimulation":
                visual = VisualSpec(
                    title=titles[index],
                    left="Rolling: successive rows",
                    right="Global: same instant",
                    parameter=0.65,
                    citation="claim-global",
                )
            elif primitives[index] == "Comparison":
                visual = VisualSpec(
                    title=titles[index],
                    left="Stationary scan",
                    right="Sliding scan",
                    citation="claim-motion-skew",
                )
            scene = Scene(
                scene_id=f"scene-{index + 1:02d}",
                order=index,
                start_time=time,
                duration=duration,
                primitive=primitives[index],
                script_segment_ids=[segment.segment_id],
                claim_ids=claim_map[index],
                on_screen_text=titles[index],
                visual=visual,
                accessibility_description=segment.text,
                evidence_label="DOCUMENTED" if claim_map[index] else None,
                dependency_hash=stable_hash(segment),
            )
            scenes.append(scene)
            time += duration
        return StoryboardManifest(
            version_id=f"storyboard-{stable_hash(scenes)[:12]}",
            script_version_id=script.version_id,
            scenes=scenes,
        )

    def critique(self, claims: ClaimsManifest) -> list[str]:
        return []
