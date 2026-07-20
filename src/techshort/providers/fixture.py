from __future__ import annotations

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
    EvidenceHighlightVisual,
    EvidenceManifest,
    EvidenceSpan,
    GridWarpVisual,
    HighlightRange,
    KineticTextVisual,
    LimitationVisual,
    RasterScanVisual,
    Scene,
    ScriptManifest,
    ScriptSegment,
    StoryboardManifest,
    TimelineEvent,
    TimelineVisual,
)


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
        copy_by_angle = {
            "surprising-result": [
                "Why can a straight rotating blade appear curved? The source explains a timing effect.",
                (
                    "A rolling-shutter sensor records image rows in sequence across a frame-"
                    "readout interval. That means not every row represents the same instant."
                ),
                (
                    "If the camera or subject moves during that interval, each row records a "
                    "different moment. Once assembled, a straight moving edge can look slanted, "
                    "and a rotating blade can look curved."
                ),
                (
                    "Think of scanning a page line by line while the paper slides sideways. "
                    "Each line can be faithful, while the assembled page appears skewed."
                ),
                (
                    "Faster motion or a longer frame readout increases the visible skew. "
                    "In the source's simple 20 ms example, the bottom-row offset is about 2%."
                ),
                "A global shutter exposes all rows together, so it avoids this row-timing skew.",
                (
                    "But that does not promise a perfect image. Motion blur, lens distortion, "
                    "stabilization, and image processing can still change the recorded geometry."
                ),
                (
                    "So a curved-looking blade can reveal row timing plus motion; it is not, by "
                    "itself, proof that the blade physically bent."
                ),
            ],
            "everyday-mechanism": [
                (
                    "A phone camera can read one picture like a scanner reads a page: line by "
                    "line, across time."
                ),
                (
                    "A rolling-shutter sensor records image rows in sequence across a frame-"
                    "readout interval, so different rows can represent different instants."
                ),
                (
                    "Motion continues while those rows are captured. Each row records a new "
                    "moment, and the assembled image can turn a straight moving edge into a "
                    "slant or curve."
                ),
                (
                    "Imagine scanning a page while the paper slides sideways. Every scanned "
                    "line can be faithful even though the assembled page looks skewed."
                ),
                (
                    "Faster motion or a longer frame readout increases the visible skew. In the "
                    "source's 20 ms example, the bottom-row offset is about 2%."
                ),
                "A global shutter exposes all rows together, avoiding this row-timing skew.",
                (
                    "That still does not guarantee perfect geometry. Motion blur, lens "
                    "distortion, stabilization, resampling, and image processing can alter the "
                    "recorded image."
                ),
                (
                    "Treat the frame as a timing map: curved-looking motion can reveal how the "
                    "sensor scanned, not prove the subject physically bent."
                ),
            ],
            "engineering-tradeoff": [
                (
                    "Camera engineers can expose every row together or scan rows in sequence. "
                    "That timing choice changes how motion appears."
                ),
                (
                    "A rolling shutter scans image rows across a frame-readout interval. It is "
                    "efficient, but the rows do not all represent one instant."
                ),
                (
                    "If the camera or subject moves during readout, successive rows capture "
                    "different moments. Assembly can turn a straight edge into a slant or a "
                    "curved blade."
                ),
                (
                    "The mechanism resembles scanning a moving page line by line: local samples "
                    "can be faithful while their combined geometry is skewed."
                ),
                (
                    "The distortion grows with motion and readout time. In the source's 20 ms "
                    "example, the bottom row is offset by about 2%."
                ),
                (
                    "A global shutter exposes all rows together and avoids this specific "
                    "row-timing skew."
                ),
                (
                    "That tradeoff is narrower than image quality overall. Blur, lens "
                    "distortion, stabilization, resampling, and processing can still change "
                    "recorded geometry."
                ),
                (
                    "So choose shutter timing for the motion you need to preserve, while "
                    "reviewing the other causes of distortion separately."
                ),
            ],
        }
        if angle not in copy_by_angle:
            raise ValueError(f"unsupported fixture angle: {angle}")
        copy = copy_by_angle[angle]
        hook_claims = (
            ["claim-global", "claim-row-timing"]
            if angle == "engineering-tradeoff"
            else ["claim-motion-skew"]
        )
        segments = [
            ScriptSegment(
                segment_id="segment-01",
                text=copy[0],
                segment_type="hook",
                claim_ids=hook_claims,
                approximate_duration=7,
            ),
            ScriptSegment(
                segment_id="segment-02",
                text=copy[1],
                segment_type="factual",
                claim_ids=["claim-row-timing"],
                approximate_duration=10,
            ),
            ScriptSegment(
                segment_id="segment-03",
                text=copy[2],
                segment_type="factual",
                claim_ids=["claim-motion-skew"],
                approximate_duration=11,
            ),
            ScriptSegment(
                segment_id="segment-04",
                text=copy[3],
                segment_type="analogy",
                claim_ids=["claim-scan-analogy"],
                approximate_duration=10,
            ),
            ScriptSegment(
                segment_id="segment-05",
                text=copy[4],
                segment_type="factual",
                claim_ids=["claim-parameters", "claim-numeric-demo"],
                approximate_duration=9,
            ),
            ScriptSegment(
                segment_id="segment-06",
                text=copy[5],
                segment_type="factual",
                claim_ids=["claim-global"],
                approximate_duration=7,
            ),
            ScriptSegment(
                segment_id="segment-07",
                text=copy[6],
                segment_type="limitation",
                claim_ids=["claim-limitation"],
                approximate_duration=9,
            ),
            ScriptSegment(
                segment_id="segment-08",
                text=copy[7],
                segment_type="cta",
                claim_ids=["claim-timing-interpretation", "claim-numeric-demo"],
                approximate_duration=8,
            ),
        ]
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

    def generate_storyboard(self, script: ScriptManifest) -> StoryboardManifest:
        primitives = [
            "KineticText",
            "EvidenceHighlight",
            "RasterScan",
            "GridWarp",
            "AnnotatedChart",
            "BeforeAfterOverlay",
            "LimitationCard",
            "Timeline",
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
        layouts = [
            "hero",
            "evidence",
            "full-diagram",
            "split",
            "numeric",
            "split",
            "limitation",
            "full-diagram",
        ]
        motions = [
            "energetic",
            "calm",
            "precise",
            "precise",
            "energetic",
            "precise",
            "calm",
            "precise",
        ]
        claim_map = [list(segment.claim_ids) for segment in script.segments]
        highlight_text = "starts or reads rows in sequence"
        highlight_start = self.phrases[0].index(highlight_text)
        visuals = [
            KineticTextVisual(
                kind="kinetic-text",
                emphasis=["straight", "curved"],
                supporting_text="The shape can come from capture timing, not bending.",
            ),
            EvidenceHighlightVisual(
                kind="evidence-highlight",
                source_title="Rolling shutter and motion",
                excerpt=self.phrases[0],
                locator="Rolling shutter and motion",
                evidence_id="evidence-01",
                highlights=[
                    HighlightRange(
                        start=highlight_start,
                        end=highlight_start + len(highlight_text),
                    )
                ],
            ),
            RasterScanVisual(
                kind="raster-scan",
                direction="top-to-bottom",
                rows=18,
                subject="blade",
                distortion=0.72,
                scan_label="successive row times",
                before_label="moving straight blade",
                after_label="assembled curved image",
            ),
            GridWarpVisual(
                kind="grid-warp",
                rows=8,
                columns=7,
                skew=0.58,
                curvature=0.18,
                before_label="page held still",
                after_label="page slides during scan",
            ),
            AnnotatedChartVisual(
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
            ),
            BeforeAfterOverlayVisual(
                kind="before-after-overlay",
                feature="straight-edge",
                before_label="rolling: successive rows",
                after_label="global: same instant",
                divider=0.52,
            ),
            LimitationVisual(
                kind="limitation",
                limitation=(
                    "A faster or global shutter does not remove blur, lens distortion, "
                    "stabilization, resampling, or processing artifacts."
                ),
                applies_when="Interpreting geometry in a captured image",
            ),
            TimelineVisual(
                kind="timeline",
                unit="ms",
                events=[
                    TimelineEvent(time=0, label="top row", detail="offset 0%"),
                    TimelineEvent(time=20, label="bottom row", detail="offset about 2%"),
                ],
            ),
        ]
        citations = [
            "Source-backed · motion during readout",
            "Exact source excerpt",
            "Source-backed · row timing",
            "Inference · scanning analogy",
            "Measured example · 20 ms",
            "Engineering comparison",
            "Important limitation",
            "Inference · timing interpretation",
        ]
        scenes: list[Scene] = []
        time = 0.0
        for index, segment in enumerate(script.segments):
            duration = segment.approximate_duration
            scene = Scene(
                scene_id=f"scene-{index + 1:02d}",
                order=index,
                start_time=time,
                duration=duration,
                primitive=primitives[index],
                layout=layouts[index],
                motion=motions[index],
                script_segment_ids=[segment.segment_id],
                claim_ids=claim_map[index],
                on_screen_text=titles[index],
                visual=visuals[index],
                accessibility_description=segment.text,
                evidence_label=("INFERRED" if index in {3, 7} else "DOCUMENTED"),
                citation_label=citations[index],
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
