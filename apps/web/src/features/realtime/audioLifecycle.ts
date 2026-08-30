export interface AudioGeneration {
  utteranceId: string
  revision: number
}

export interface AudioEndDecision {
  accepted: boolean
  shouldSend: boolean
}

/** Decide whether an audio_end belongs to the active generation. */
export function decideAudioEnd(
  active: AudioGeneration | undefined,
  requested: AudioGeneration | undefined,
  transportReady: boolean,
): AudioEndDecision {
  const accepted = Boolean(
    active
    && requested
    && active.utteranceId === requested.utteranceId
    && active.revision === requested.revision,
  )
  return { accepted, shouldSend: accepted && transportReady }
}
