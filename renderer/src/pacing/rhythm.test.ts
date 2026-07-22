import { describe, expect, it } from "vitest";
import {
  coldOpenSignal,
  captionMotionFor,
  kineticEntrancePresentationFor,
  microBeatFrames,
  microBeatSignal,
  pacingProfiles,
  patternInterruptFor,
  sceneProgressFor,
  transitionFramesFor,
  transitionPresentationFor,
} from "./rhythm";

describe("retention pacing", () => {
  it("keeps every preset inside accessible motion bounds", () => {
    expect(Object.keys(pacingProfiles)).toEqual([
      "measured",
      "brisk",
      "high-retention",
    ]);
    for (const profile of Object.values(pacingProfiles)) {
      expect(profile.microBeatCount).toBeLessThanOrEqual(4);
      expect(profile.transitionSeconds).toBeGreaterThanOrEqual(0.18);
      expect(profile.decorationOpacity).toBeLessThanOrEqual(0.11);
      expect(profile.decorationShift).toBeLessThanOrEqual(8);
    }
  });

  it("places bounded micro-beats away from scene cuts", () => {
    const beats = microBeatFrames(180, 30, "high-retention");
    expect(beats).toHaveLength(4);
    expect(beats[0]).toBeGreaterThanOrEqual(17);
    expect(beats.at(-1)).toBeLessThanOrEqual(163);
    for (let index = 1; index < beats.length; index += 1) {
      expect(beats[index]! - beats[index - 1]!).toBeGreaterThanOrEqual(24);
    }
    expect(microBeatFrames(30, 30, "high-retention")).toEqual([]);
  });

  it("uses gradual pulses rather than one-frame flashes", () => {
    const beat = microBeatFrames(180, 30, "brisk")[0]!;
    expect(microBeatSignal(beat, 180, 30, "brisk")).toBe(1);
    expect(microBeatSignal(beat - 1, 180, 30, "brisk")).toBeGreaterThan(0.8);
    expect(microBeatSignal(beat - 8, 180, 30, "brisk")).toBe(0);
  });

  it("keeps Kinetic Pop completely stable after its scene boundary", () => {
    const stable = {
      translateX: 0,
      revealInsetLeft: 0,
      revealInsetRight: 0,
    };
    for (const transition of ["cut", "fade", "slide"] as const) {
      for (const frame of [6, 7, 30, 90, 180]) {
        expect(kineticEntrancePresentationFor(frame, 6, 1, transition)).toEqual(
          stable,
        );
      }
    }
  });

  it("uses only bounded deterministic slides or masked reveals", () => {
    const cut = kineticEntrancePresentationFor(0, 6, 1, "cut");
    expect(cut).toEqual({
      translateX: 0,
      revealInsetLeft: 0,
      revealInsetRight: 0,
    });

    const slide = kineticEntrancePresentationFor(0, 6, 1, "slide");
    expect(slide).toMatchObject({
      translateX: -28,
      revealInsetLeft: 0,
      revealInsetRight: 0,
    });
    expect("scale" in slide).toBe(false);
    expect("translateY" in slide).toBe(false);
    const slideMidpoint = kineticEntrancePresentationFor(3, 6, 1, "slide");
    expect(slideMidpoint.translateX).toBeGreaterThan(-28);
    expect(slideMidpoint.translateX).toBeLessThan(0);

    expect(kineticEntrancePresentationFor(0, 6, 0, "fade")).toMatchObject({
      translateX: 0,
      revealInsetLeft: 0,
      revealInsetRight: 100,
    });
    expect(kineticEntrancePresentationFor(0, 6, 1, "fade")).toMatchObject({
      revealInsetLeft: 100,
      revealInsetRight: 0,
    });
    const maskedMidpoint = kineticEntrancePresentationFor(3, 6, 1, "fade");
    expect(maskedMidpoint).toEqual({
      translateX: 0,
      revealInsetLeft: 50,
      revealInsetRight: 0,
    });
    expect(kineticEntrancePresentationFor(3, 6, 1, "fade")).toEqual(
      maskedMidpoint,
    );
  });

  it("makes the cold open immediate and deterministic", () => {
    expect(coldOpenSignal(0, 30)).toBe(1);
    expect(coldOpenSignal(10, 30)).toBeGreaterThan(0);
    expect(coldOpenSignal(21, 30)).toBe(0);
    expect(sceneProgressFor(0, 60)).toBe(0);
    expect(sceneProgressFor(59, 60)).toBe(1);
  });

  it("keeps caption entrances readable and adds continuous phrase progress", () => {
    expect(captionMotionFor(2, 2, 4)).toEqual({
      opacity: 0.86,
      translateY: 10,
      progress: 0,
    });
    const entered = captionMotionFor(2.2, 2, 4);
    expect(entered.opacity).toBe(1);
    expect(entered.translateY).toBe(0);
    expect(entered.progress).toBeCloseTo(0.1);
    expect(captionMotionFor(4, 2, 4).opacity).toBe(1);
  });

  it("cycles allowlisted pattern interrupts and bounds transitions", () => {
    expect([0, 1, 2, 3].map(patternInterruptFor)).toEqual([
      "accent-rail",
      "corner-brackets",
      "focus-ring",
      "accent-rail",
    ]);
    const frames = transitionFramesFor(
      { duration: 1, motion: "energetic" },
      30,
      "high-retention",
    );
    expect(frames).toBeGreaterThanOrEqual(1);
    expect(frames).toBeLessThanOrEqual(10);
    expect(
      transitionPresentationFor(0, frames, "fade", "precise", true),
    ).toEqual({ opacity: 1, translateX: 0 });
    expect(
      transitionPresentationFor(frames, frames, "slide", "precise", false),
    ).toEqual({ opacity: 1, translateX: 0 });
    expect(
      transitionPresentationFor(0, frames, "fade", "precise", false),
    ).toEqual({ opacity: 1, translateX: 0 });
    expect(
      transitionPresentationFor(0, frames, "slide", "precise", false),
    ).toEqual({ opacity: 1, translateX: 48 });
    expect(
      transitionPresentationFor(frames * 8, frames, "fade", "precise", false)
        .opacity,
    ).toBe(1);
  });
});
