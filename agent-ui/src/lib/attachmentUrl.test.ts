// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { beforeEach, describe, expect, it, vi } from "vitest";

const connection = vi.hoisted(() => ({
  brainEndpoint: "http://127.0.0.1:5001",
  proxyEndpoint: "",
  channel: "web" as const,
  sessionId: undefined as string | undefined,
}));

vi.mock("@/store/connectionStore", () => ({
  getConnectionConfig: () => ({ ...connection }),
}));

import {
  deriveAttachFileName,
  isImageAttachment,
  parseUploadRef,
  resolveUploadContentUrl,
} from "@/lib/attachmentUrl";

describe("parseUploadRef", () => {
  it("splits a session-qualified ref", () => {
    expect(parseUploadRef("upload://sess_a/pic.png_1700000000000")).toEqual({
      sessionId: "sess_a",
      storedName: "pic.png_1700000000000",
    });
  });

  it("treats a legacy ref as sessionless", () => {
    expect(parseUploadRef("upload://pic.png_1700000000000")).toEqual({
      sessionId: "",
      storedName: "pic.png_1700000000000",
    });
  });

  it("ignores a real path", () => {
    expect(parseUploadRef("/Users/me/pic.png")).toBeNull();
    expect(parseUploadRef(null)).toBeNull();
  });
});

describe("deriveAttachFileName", () => {
  it("drops the scheme, the session and the upload timestamp", () => {
    expect(
      deriveAttachFileName("upload://sess_a/pic.png_1700000000000")
    ).toBe("pic.png");
  });
});

describe("isImageAttachment", () => {
  it("looks past the stored timestamp", () => {
    expect(isImageAttachment("upload://sess_a/pic.png_1700000000000")).toBe(
      true
    );
    expect(isImageAttachment("upload://sess_a/notes.txt_1700000000000")).toBe(
      false
    );
  });
});

describe("resolveUploadContentUrl", () => {
  beforeEach(() => {
    connection.sessionId = undefined;
  });

  it("uses the session embedded in the ref", () => {
    connection.sessionId = "sess_connection";
    expect(
      resolveUploadContentUrl("upload://sess_upload/pic.png_1700000000000")
    ).toBe(
      "http://127.0.0.1:5001/files/upload-content" +
        "?file_id=upload%3A%2F%2Fsess_upload%2Fpic.png_1700000000000" +
        "&session_id=sess_upload"
    );
  });

  it("still builds a URL for a legacy ref with no session anywhere", () => {
    // The Brain resolves by the unique stored name, so dropping the URL here
    // would leave the attachment unopenable for no reason.
    expect(resolveUploadContentUrl("upload://pic.png_1700000000000")).toBe(
      "http://127.0.0.1:5001/files/upload-content" +
        "?file_id=upload%3A%2F%2Fpic.png_1700000000000"
    );
  });

  it("falls back to the connection session for a legacy ref", () => {
    connection.sessionId = "sess_connection";
    expect(resolveUploadContentUrl("upload://pic.png_1700000000000")).toContain(
      "&session_id=sess_connection"
    );
  });

  it("returns null for a real filesystem path", () => {
    expect(resolveUploadContentUrl("/Users/me/pic.png")).toBeNull();
  });
});
