import type { CSSProperties } from "react";

import type { CaptionTokenData } from "../schemas/project";

export const MIN_EMPHASIS_HOLD_SECONDS = 0.4;
export const MAX_EMPHASIS_CHANGES_PER_SECOND = 1 / MIN_EMPHASIS_HOLD_SECONDS;

export type EmphasisPhrase = {
  start: number;
  end: number;
  tokenIndexes: number[];
};

const groupedTokenPhrases = (
  tokens: readonly CaptionTokenData[],
  cueEnd: number,
): EmphasisPhrase[] => {
  const groups: EmphasisPhrase[] = [];
  tokens.forEach((token, tokenIndex) => {
    const current = groups.at(-1);
    if (current && tokens[current.tokenIndexes[0]!]!.group === token.group) {
      current.end = token.end;
      current.tokenIndexes.push(tokenIndex);
      return;
    }
    groups.push({
      start: token.start,
      end: token.end,
      tokenIndexes: [tokenIndex],
    });
  });

  return groups.map((group, groupIndex) => ({
    ...group,
    // Hold a phrase until the next phrase begins. This avoids a distracting
    // underline blink during natural gaps while every word remains readable.
    end: groups[groupIndex + 1]?.start ?? Math.max(group.end, cueEnd),
  }));
};

export const emphasisPhrasesFor = (
  tokens: readonly CaptionTokenData[],
  cueEnd: number,
  minimumHoldSeconds = MIN_EMPHASIS_HOLD_SECONDS,
): EmphasisPhrase[] => {
  if (tokens.length === 0) return [];
  if (!Number.isFinite(cueEnd) || !Number.isFinite(minimumHoldSeconds))
    return [];
  if (minimumHoldSeconds <= 0) return groupedTokenPhrases(tokens, cueEnd);

  const accessible: EmphasisPhrase[] = [];
  let pending: EmphasisPhrase | undefined;
  for (const phrase of groupedTokenPhrases(tokens, cueEnd)) {
    if (!pending) {
      pending = { ...phrase, tokenIndexes: [...phrase.tokenIndexes] };
      continue;
    }
    if (pending.end - pending.start + Number.EPSILON < minimumHoldSeconds) {
      pending.end = phrase.end;
      pending.tokenIndexes.push(...phrase.tokenIndexes);
      continue;
    }
    accessible.push(pending);
    pending = { ...phrase, tokenIndexes: [...phrase.tokenIndexes] };
  }
  if (!pending) return accessible;
  if (
    pending.end - pending.start + Number.EPSILON < minimumHoldSeconds &&
    accessible.length > 0
  ) {
    const previous = accessible.at(-1)!;
    previous.end = pending.end;
    previous.tokenIndexes.push(...pending.tokenIndexes);
  } else {
    accessible.push(pending);
  }
  return accessible;
};

export const activeEmphasisTokenIndexes = (
  tokens: readonly CaptionTokenData[],
  currentTime: number,
  cueEnd: number,
): number[] =>
  emphasisPhrasesFor(tokens, cueEnd).find(
    (phrase) => currentTime >= phrase.start && currentTime < phrase.end,
  )?.tokenIndexes ?? [];

export const captionTokenPresentation = (
  active: boolean,
  accent: string,
): CSSProperties => ({
  color: "#f7f9ff",
  opacity: 1,
  textDecorationLine: active ? "underline" : "none",
  textDecorationColor: accent,
  textDecorationStyle: "solid",
  textDecorationThickness: 5,
  textUnderlineOffset: 7,
  textDecorationSkipInk: "none",
});
