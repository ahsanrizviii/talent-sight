// Takes one still picture from a playing video element, as a JPEG data URL (Module 13, F7).
// It is only sent to the server, which reads it in memory and keeps numbers, never the picture.
// drawImage uses the camera's own picture, not the mirrored preview.
export function grabFrame(video: HTMLVideoElement | null, maxWidth = 640): string {
  if (!video || video.readyState < 2 || !video.videoWidth) return "";
  const scale = Math.min(1, maxWidth / video.videoWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  const context = canvas.getContext("2d");
  if (!context) return "";
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}