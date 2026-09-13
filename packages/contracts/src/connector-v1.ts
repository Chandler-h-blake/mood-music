export const CONNECTOR_PROTOCOL_VERSION = "1.0" as const;

export type ConnectorType = "web" | "pc";
export type ConnectorCapability =
  | "catalog.search"
  | "queue.play"
  | "playback.control"
  | "playback.state";

export type PlaybackAction = "play" | "pause" | "resume" | "next" | "previous" | "stop";
export type PlaybackStatus =
  | "idle"
  | "loading"
  | "playing"
  | "paused"
  | "stopped"
  | "ended"
  | "error";

export interface TrackReference {
  sourceTrackId: string;
  title: string;
  artists: string[];
  album?: string | null;
  durationMs?: number | null;
}

export interface MessageEnvelope<TType extends string, TPayload> {
  protocolVersion: typeof CONNECTOR_PROTOCOL_VERSION;
  type: TType;
  requestId: string;
  sentAt: string;
  payload: TPayload;
}

export type ConnectorHelloMessage = MessageEnvelope<
  "connector.hello",
  {
    installationId: string;
    connectorType: ConnectorType;
    connectorVersion: string;
    targetAppVersion: string;
    adapterVersion: string;
    capabilities: ConnectorCapability[];
  }
>;

export type ConnectorWelcomeMessage = MessageEnvelope<
  "connector.welcome",
  {
    accepted: true;
    connectorType: ConnectorType;
    serverVersion: string;
    negotiatedCapabilities: ConnectorCapability[];
    heartbeatIntervalSeconds: number;
  }
>;

export type ConnectorHeartbeatMessage = MessageEnvelope<
  "connector.heartbeat",
  {
    installationId: string;
    status: "ready" | "degraded";
    activeTarget: boolean;
    currentTrackId?: string | null;
  }
>;

export type CatalogSearchRequestedMessage = MessageEnvelope<
  "catalog.searchRequested",
  { query: string; expectedTrack: TrackReference; limit: number }
>;

export type CatalogSearchCompletedMessage = MessageEnvelope<
  "catalog.searchCompleted",
  {
    results: Array<{
      sourceTrackId: string;
      title: string;
      artists: string[];
      album?: string | null;
      playable?: boolean | null;
      confidence: number;
    }>;
  }
>;

export type PlaybackQueueRequestedMessage = MessageEnvelope<
  "playback.queueRequested",
  {
    playlistId: string;
    snapshotHash: string;
    stopAfterLast: true;
    tracks: TrackReference[];
  }
>;

export type PlaybackQueueAcceptedMessage = MessageEnvelope<
  "playback.queueAccepted",
  {
    playlistId: string;
    snapshotHash: string;
    acceptedTrackIds: string[];
    rejectedTrackIds: string[];
  }
>;

export type PlaybackQueueRejectedMessage = MessageEnvelope<
  "playback.queueRejected",
  {
    playlistId: string;
    snapshotHash: string;
    code:
      | "connector.notReady"
      | "connector.capabilityMissing"
      | "connector.targetIncompatible"
      | "queue.snapshotMismatch"
      | "queue.trackNotFound"
      | "queue.trackUnplayable"
      | "queue.ambiguousTrack"
      | "queue.operationFailed";
    message: string;
  }
>;

export type PlaybackActionRequestedMessage = MessageEnvelope<
  "playback.actionRequested",
  { action: PlaybackAction; playlistId?: string | null }
>;

export type PlaybackStateChangedMessage = MessageEnvelope<
  "playback.stateChanged",
  {
    status: PlaybackStatus;
    playlistId?: string | null;
    sourceTrackId?: string | null;
    positionMs?: number | null;
    durationMs?: number | null;
    queueIndex?: number | null;
    errorCode?: string | null;
  }
>;

export type ConnectorMessage =
  | ConnectorHelloMessage
  | ConnectorWelcomeMessage
  | ConnectorHeartbeatMessage
  | CatalogSearchRequestedMessage
  | CatalogSearchCompletedMessage
  | PlaybackQueueRequestedMessage
  | PlaybackQueueAcceptedMessage
  | PlaybackQueueRejectedMessage
  | PlaybackActionRequestedMessage
  | PlaybackStateChangedMessage;

export type ConnectorCommand =
  | CatalogSearchRequestedMessage
  | PlaybackQueueRequestedMessage
  | PlaybackActionRequestedMessage;

export type ConnectorEvent =
  | ConnectorHeartbeatMessage
  | CatalogSearchCompletedMessage
  | PlaybackQueueAcceptedMessage
  | PlaybackQueueRejectedMessage
  | PlaybackStateChangedMessage;

/** Implemented independently by the Chrome content adapter and Windows PC helper. */
export interface ConnectorAdapter {
  readonly connectorType: ConnectorType;
  readonly connectorVersion: string;
  readonly targetAppVersion: string;
  readonly adapterVersion: string;
  readonly capabilities: readonly ConnectorCapability[];

  handle(command: ConnectorCommand): Promise<ConnectorEvent>;
}
