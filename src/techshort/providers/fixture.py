from __future__ import annotations

from techshort.domain.creative import BeatPlan, NarrativeBrief, RetentionPlan
from techshort.domain.hashing import stable_hash
from techshort.domain.models import (
    AngleCandidate,
    AnglesManifest,
    AnnotatedChartVisual,
    BeforeAfterOverlayVisual,
    ChartAnnotation,
    ChartAxis,
    ChartPoint,
    ChartSeries,
    Claim,
    ClaimsManifest,
    ComparisonSide,
    ComparisonVisual,
    EdgeSpec,
    EvidenceHighlightVisual,
    EvidenceManifest,
    EvidenceSpan,
    GridWarpVisual,
    HighlightRange,
    KineticTextVisual,
    LimitationVisual,
    MechanismDiagramVisual,
    NodeSpec,
    ParameterSimulationVisual,
    RasterScanVisual,
    Scene,
    ScriptManifest,
    SourceReceiptVisual,
    StoryboardManifest,
    TypedVisualSpec,
)
from techshort.generation.editorial.beats import rolling_shutter_beats
from techshort.generation.editorial.retention import build_rolling_shutter_retention_plan
from techshort.generation.editorial.script import rolling_shutter_script_segments


class FixtureProvider:
    """Deterministic provider for the original rolling-shutter fixture."""

    phrases = [
        (
            "A rolling-shutter sensor does not expose every image row at the same instant. "
            "Instead, it starts or reads rows in sequence over a frame-readout interval."
        ),
        (
            "If an object or camera moves during that interval, each row records a slightly "
            "different moment. When the rows are assembled, a straight moving edge can appear "
            "slanted and a rotating blade can appear curved."
        ),
        "Faster motion or a longer frame readout increases the visible skew.",
        "A global shutter exposes all rows together and therefore avoids this row-timing skew.",
        (
            "A faster readout reduces distortion, but it does not guarantee a perfectly "
            "undistorted image. Motion blur, lens distortion, stabilization, resampling, and "
            "image processing can still change recorded geometry."
        ),
        (
            "A simple demonstration assigns row 0 to time 0 ms and row 1000 to time 20 ms. "
            "If an edge moves horizontally at 1 image-width per second during that readout, "
            "the top-row offset is 0% and the bottom row records the edge about 2% of an "
            "image-width later."
        ),
    ]
    section_headings = [
        "Rolling shutter and motion",
        "Rolling shutter and motion",
        "Rolling shutter and motion",
        "Engineering comparison",
        "Engineering comparison",
        "Rolling shutter and motion",
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
                    section_heading=self.section_headings[index - 1],
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
                limitation=(
                    "Motion blur, lens distortion, stabilization, resampling, and image "
                    "processing can still change recorded geometry."
                ),
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-numeric-demo",
                text=self.phrases[5],
                evidence_span_ids=["evidence-06"],
                relationship="direct",
                evidence_label="documented",
                scope="A simplified 20 ms readout example with steady horizontal motion.",
                confidence=1.0,
            ),
            Claim(
                claim_id="claim-scan-analogy",
                text=(
                    "Sequential row capture during motion can be compared to scanning while "
                    "the subject moves."
                ),
                evidence_span_ids=["evidence-01", "evidence-02"],
                relationship="synthesis",
                evidence_label="inferred",
                reasoning=(
                    "The analogy combines documented sequential row timing with documented "
                    "motion during the readout interval."
                ),
                confidence=0.9,
            ),
            Claim(
                claim_id="claim-timing-interpretation",
                text=(
                    "Apparent blade curvature can reflect row timing plus motion rather than "
                    "proving that the blade itself bent."
                ),
                evidence_span_ids=["evidence-01", "evidence-02"],
                relationship="synthesis",
                evidence_label="inferred",
                reasoning=(
                    "The source documents a rotating blade appearing curved when rows capture "
                    "different moments; the interpretation preserves that appearance-versus-"
                    "shape distinction."
                ),
                confidence=0.95,
            ),
        ]
        return ClaimsManifest(
            version_id=f"claims-{stable_hash(claims)[:12]}",
            evidence_version_id=evidence.version_id,
            claims=claims,
        )

    def generate_angles(self, claims: ClaimsManifest) -> AnglesManifest:
        candidates = [
            AngleCandidate(
                angle="surprising-result",
                title="A straight blade can look curved",
                rationale=(
                    "Lead with the counterintuitive visible result, then resolve it as a "
                    "row-timing effect rather than evidence that the blade physically bent."
                ),
                central_claim_ids=["claim-motion-skew", "claim-timing-interpretation"],
            ),
            AngleCandidate(
                angle="everyday-mechanism",
                title="A camera frame is scanned across time",
                rationale=(
                    "Use the familiar idea of scanning line by line to explain how motion "
                    "during sequential row capture becomes skew in the assembled frame."
                ),
                central_claim_ids=["claim-row-timing", "claim-scan-analogy"],
            ),
            AngleCandidate(
                angle="engineering-tradeoff",
                title="Rolling and global shutters trade timing behavior",
                rationale=(
                    "Contrast sequential and simultaneous exposure while preserving the "
                    "important limitation that a global shutter does not remove every source "
                    "of image distortion."
                ),
                central_claim_ids=["claim-global", "claim-limitation"],
            ),
        ]
        return AnglesManifest(
            version_id=f"angles-{stable_hash(candidates)[:12]}",
            claims_version_id=claims.version_id,
            candidates=candidates,
        )

    def generate_script(
        self,
        claims: ClaimsManifest,
        angle: str,
        *,
        angles_version_id: str | None = None,
        angle_selection_id: str | None = None,
    ) -> ScriptManifest:
        segments = rolling_shutter_script_segments(angle)
        return ScriptManifest(
            version_id=f"script-{stable_hash(segments)[:12]}",
            claims_version_id=claims.version_id,
            angles_version_id=angles_version_id
            or f"angles-direct-{stable_hash({'claims': claims.version_id})[:12]}",
            angle_selection_id=angle_selection_id
            or f"selection-direct-{stable_hash({'claims': claims.version_id, 'angle': angle})[:12]}",
            angle=angle,
            segments=segments,
        )

    def generate_retention_plan(
        self,
        brief: NarrativeBrief,
        beat_plan: BeatPlan,
        script: ScriptManifest,
    ) -> RetentionPlan:
        return build_rolling_shutter_retention_plan(brief, beat_plan, script)

    def _storyboard_visual(self, angle: str, order: int, primitive: str) -> TypedVisualSpec:
        if primitive == "KineticText":
            return KineticTextVisual(
                kind="kinetic-text",
                emphasis=["rows", "successive moments"],
                supporting_text="Rolling shutter records rows in sequence.",
            )
        if primitive == "BeforeAfterOverlay":
            if angle == "engineering-tradeoff":
                before_label = "rolling: successive row times"
                after_label = "global: one shared time"
            elif order == 0:
                before_label = "physical straight blade"
                after_label = "captured curved silhouette"
            else:
                before_label = "moving straight blade"
                after_label = "assembled timing map"
            return BeforeAfterOverlayVisual(
                kind="before-after-overlay",
                feature="straight-edge",
                before_label=before_label,
                after_label=after_label,
                divider=0.52,
            )
        if primitive == "RasterScan":
            if angle == "everyday-mechanism":
                return RasterScanVisual(
                    kind="raster-scan",
                    direction="top-to-bottom",
                    rows=18,
                    subject="grid",
                    distortion=0.62,
                    scan_label="scanner moves line by line",
                    before_label="page moving sideways",
                    after_label="assembled skewed page",
                )
            return RasterScanVisual(
                kind="raster-scan",
                direction="top-to-bottom",
                rows=18,
                subject="blade",
                distortion=0.72,
                scan_label="successive row times",
                before_label="moving straight blade",
                after_label="assembled curved image",
            )
        if primitive == "GridWarp":
            if angle == "surprising-result":
                before_label = "straight moving blade"
                after_label = "curved recorded silhouette"
            else:
                before_label = "faithful scanned lines"
                after_label = "skewed assembled page"
            return GridWarpVisual(
                kind="grid-warp",
                rows=8,
                columns=7,
                skew=0.58,
                curvature=0.18,
                before_label=before_label,
                after_label=after_label,
            )
        if primitive == "EvidenceHighlight":
            highlight = "time 0 ms and row 1000 to time 20 ms"
            highlight_start = self.phrases[5].index(highlight)
            return EvidenceHighlightVisual(
                kind="evidence-highlight",
                source_title="Rolling shutter and motion",
                excerpt=self.phrases[5],
                locator="Rolling shutter and motion",
                evidence_id="evidence-06",
                highlights=[
                    HighlightRange(
                        start=highlight_start,
                        end=highlight_start + len(highlight),
                    )
                ],
            )
        if primitive == "SourceReceipt":
            return SourceReceiptVisual(
                kind="source-receipt",
                source_title="Rolling shutter and motion",
                excerpt=self.phrases[5],
                locator="Rolling shutter and motion",
                evidence_id="evidence-06",
                highlight="20 ms",
            )
        if primitive == "ChartReveal":
            return AnnotatedChartVisual(
                kind="annotated-chart",
                chart_type="line",
                x_axis=ChartAxis(label="row capture time", unit="ms"),
                y_axis=ChartAxis(label="horizontal offset", unit="% image width"),
                series=[
                    ChartSeries(
                        label="simplified source example",
                        color="warning",
                        points=[ChartPoint(x=0, y=0), ChartPoint(x=20, y=2)],
                    )
                ],
                annotations=[ChartAnnotation(x=20, y=2, label="bottom row: about 2%")],
            )
        if primitive == "MechanismDiagram":
            if order == 7:
                nodes = [
                    NodeSpec(id="rows", label="successive rows", x=0.15, y=0.5),
                    NodeSpec(id="moments", label="different moments", x=0.5, y=0.5),
                    NodeSpec(id="frame", label="assembled frame", x=0.85, y=0.5),
                ]
                edges = [
                    EdgeSpec(source="rows", target="moments", label="capture"),
                    EdgeSpec(source="moments", target="frame", label="assemble"),
                ]
            else:
                nodes = [
                    NodeSpec(id="top", label="top sensor row", x=0.2, y=0.2),
                    NodeSpec(id="middle", label="successive rows", x=0.5, y=0.5),
                    NodeSpec(id="bottom", label="bottom sensor row", x=0.8, y=0.8),
                ]
                edges = [
                    EdgeSpec(source="top", target="middle", label="then"),
                    EdgeSpec(source="middle", target="bottom", label="then"),
                ]
            return MechanismDiagramVisual(
                kind="mechanism-diagram",
                nodes=nodes,
                edges=edges,
                active_step_id="moments" if order == 7 else "middle",
            )
        if primitive == "ParameterSimulation":
            return ParameterSimulationVisual(
                kind="parameter-simulation",
                parameter_label="frame readout",
                unit="ms",
                minimum=0,
                maximum=20,
                value=20,
                left_label="shorter readout",
                right_label="longer readout",
            )
        if primitive == "Comparison":
            if angle == "engineering-tradeoff" and order == 4:
                left = ComparisonSide(
                    label="Specific fix",
                    value="avoids row-timing skew",
                    detail="shared exposure timing",
                    distorted=False,
                )
                right = ComparisonSide(
                    label="Remaining limit",
                    value="other distortions remain",
                    detail="optics, blur, stabilization, processing",
                    distorted=True,
                )
            else:
                left = ComparisonSide(
                    label="Rolling",
                    value="successive row times",
                    detail="motion can become skew",
                    distorted=True,
                )
                right = ComparisonSide(
                    label="Global",
                    value="one shared exposure time",
                    detail="avoids this row-timing skew",
                    distorted=False,
                )
            return ComparisonVisual(
                kind="comparison", feature="straight-edge", left=left, right=right
            )
        if primitive == "LimitationCard":
            return LimitationVisual(
                kind="limitation",
                limitation=(
                    "Avoiding row-timing skew does not remove blur, lens distortion, "
                    "stabilization, resampling, or processing effects."
                ),
                applies_when="Interpreting geometry in a captured image",
            )
        raise ValueError(f"unsupported fixture storyboard primitive: {primitive}")

    @staticmethod
    def _storyboard_citation(claim_ids: list[str]) -> str:
        claims = set(claim_ids)
        if claims & {"claim-scan-analogy", "claim-timing-interpretation"}:
            return "Inference · source-linked synthesis"
        if "claim-numeric-demo" in claims:
            return "Measured example · 20 ms readout"
        if "claim-limitation" in claims:
            return "Documented limitation · image geometry"
        if "claim-global" in claims:
            return "Documented · rolling and global timing"
        if "claim-motion-skew" in claims:
            return "Documented · motion during readout"
        return "Documented · sequential row timing"

    def generate_storyboard(self, script: ScriptManifest) -> StoryboardManifest:
        beats = rolling_shutter_beats(script.angle)
        if len(beats) != len(script.segments):
            raise ValueError("fixture storyboard requires one beat per script segment")
        layout_map = {
            "hero": "hero",
            "full-diagram": "full-diagram",
            "split-comparison": "split",
            "evidence-receipt": "evidence",
            "numeric-result": "numeric",
            "limitation": "limitation",
        }
        scenes: list[Scene] = []
        time = 0.0
        inferred_claim_ids = {"claim-scan-analogy", "claim-timing-interpretation"}
        for index, (beat, segment) in enumerate(zip(beats, script.segments, strict=True)):
            if set(beat.claim_ids) != set(segment.claim_ids):
                raise ValueError(
                    f"fixture beat {beat.beat_id} claim links do not match {segment.segment_id}"
                )
            duration = segment.approximate_duration
            scene = Scene(
                scene_id=f"scene-{index + 1:02d}",
                order=index,
                start_time=time,
                duration=duration,
                primitive=beat.primitive_hint,
                layout=layout_map[beat.layout_family],
                motion=(
                    "energetic"
                    if beat.role in {"hook", "re-hook"}
                    else "calm"
                    if beat.role == "limitation"
                    else "precise"
                ),
                script_segment_ids=[segment.segment_id],
                claim_ids=list(segment.claim_ids),
                on_screen_text=beat.on_screen_text,
                visual=self._storyboard_visual(script.angle, index, beat.primitive_hint),
                accessibility_description=segment.text,
                evidence_label=(
                    "INFERRED"
                    if inferred_claim_ids.intersection(segment.claim_ids)
                    else "DOCUMENTED"
                ),
                citation_label=self._storyboard_citation(segment.claim_ids),
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
