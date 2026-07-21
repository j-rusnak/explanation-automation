# Rights handling

techshort defaults to original diagrams, charts, text, and animations. Each external asset records creator, origin, URL when relevant, license, attribution, embedding permission, human review, and scene use. Original, user-owned, and permissively licensed assets may be embedded after review. Citation-only, unknown, and restricted assets block export.

Source documents, raw page extraction, and normalized full text remain local and are excluded from exports. The evidence page uses only short excerpts needed for verification. Fonts, music, footage, figures, datasets, and voices are assets and require the same review. Redrawing a protected figure is not assumed to resolve copyright. Paywalled material is never redistributed.

Narration is probed as real media before import and becomes a rights-tracked asset. A permissively licensed recording requires concrete creator and license metadata; placeholder license text cannot pass. User-owned/original assertions still require explicit human rights approval. An optional UTF-8 transcript is bound to the exact audio hash for script-comparison QA and remains local.

Local synthetic narration follows the same rule, whether it comes from Kokoro or the Windows
System.Speech fallback. User recording is not required, but synthetic generation does not bypass
the rights gate. The pinned `kokoro-js` runtime and pinned Kokoro ONNX model are Apache-2.0; that
software/model license does not by itself classify a selected stock voice or generated WAV as
original, user-owned, or commercially reusable. Kokoro voice/output rights therefore remain
`unknown` until a human reviews the applicable terms and records an accurate rights status,
license, and attribution. A WAV produced by the low-level Node helper must enter the normal asset
workflow before it can be embedded.

Windows System.Speech voice availability likewise does not establish a right to distribute
generated output. The `audio synthesize --provider sapi` path records the installed voice and
synthesis settings but defaults rights status to `unknown`. Kokoro uses the same safe default.
That status blocks embedding and final
export until the operator reviews the applicable operating-system, voice, and output terms. Do
not assume that local, bundled, zero-cost, or Apache-2.0 software automatically grants output
rights. techshort supports only allowlisted or installed stock voices and does not implement voice
cloning.

The one-time Kokoro model cache lives under the Git-ignored `.techshort/` directory. It is a local
runtime dependency, not a project asset, and is excluded from exports. Anyone redistributing the
runtime or model separately remains responsible for preserving the Apache-2.0 notices and meeting
all applicable license conditions.

Projects require narration by default. `silent-reviewed` is an explicit production choice for a caption-led export, not a rights workaround or an automatic fallback when audio metadata is incomplete.

Retention-plan sound cues are allowlisted, inert editorial metadata. They cannot name a file or
URL. `audio sound-design` may turn those enums into a quiet deterministic procedural track made by
techshort without downloaded recordings or samples. The generated WAV is recorded as an original
asset but still requires human rights approval before embedding. Imported music or effects remain
separate assets and require creator/origin, license, embedding permission, attribution, and human
review. Any audio change invalidates affected preview, QA, and final approvals.

Organic publication packages copy only already reviewed media, cover, caption sidecars, post
metadata, checklist, and consent receipt. The consent receipt authorizes manual use of that exact
package; it is not a license for source material or a guarantee that platform music, stickers,
fonts, or other composer additions are cleared. Record any material added during manual posting
outside techshort under the operator's normal rights process.

The renderer uses Atkinson Hyperlegible under SIL OFL 1.1 and records it in the asset manifest. The
pinned Kokoro runtime/model are Apache-2.0 software dependencies with the voice/output distinction
described above. Remotion itself is a software dependency with separate licensing terms;
eligibility must be evaluated for the operator's organization and use.

The generated asset-rights report is an organizational aid, not a guarantee of legal clearance.
