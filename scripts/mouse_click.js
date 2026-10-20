// Real left click at screen point X Y (needs Accessibility for the app that runs it).
// usage: osascript -l JavaScript scripts/mouse_click.js X Y
ObjC.import('CoreGraphics');
function run(argv) {
  const p = $.CGPointMake(Number(argv[0]), Number(argv[1]));
  const post = (type) => $.CGEventPost($.kCGHIDEventTap, $.CGEventCreateMouseEvent($(), type, p, $.kCGMouseButtonLeft));
  post($.kCGEventMouseMoved);
  delay(0.15);
  post($.kCGEventLeftMouseDown);
  delay(0.05);
  post($.kCGEventLeftMouseUp);
  return 'clicked';
}
