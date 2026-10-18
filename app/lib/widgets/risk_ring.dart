import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// The watch ring: Chaukanna's signature. A 270-degree ring of four segments that
/// fills as the risk climbs and takes the call type's colour. With [breathe] it
/// swells slowly, like something awake and watching; it stands still when the
/// phone asks for reduced motion. [child] sits in the middle.
class RiskRing extends StatefulWidget {
  const RiskRing({
    super.key,
    required this.litSegments,
    required this.color,
    required this.size,
    required this.child,
    this.breathe = false,
    this.semanticsLabel,
  });

  final int litSegments; // 0..4
  final Color color;
  final double size;
  final Widget child;
  final bool breathe;
  final String? semanticsLabel;

  @override
  State<RiskRing> createState() => _RiskRingState();
}

class _RiskRingState extends State<RiskRing> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2600));

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final still = MediaQuery.of(context).disableAnimations || !widget.breathe;
    if (still) {
      _c.stop();
      _c.value = 0;
    } else if (!_c.isAnimating) {
      _c.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(covariant RiskRing old) {
    super.didUpdateWidget(old);
    didChangeDependencies();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: widget.semanticsLabel,
      excludeSemantics: widget.semanticsLabel != null,
      child: SizedBox(
        width: widget.size,
        height: widget.size,
        child: TweenAnimationBuilder<Color?>(
          tween: ColorTween(end: widget.color),
          duration: const Duration(milliseconds: 500),
          builder: (context, color, child) => TweenAnimationBuilder<double>(
            tween: Tween(end: widget.litSegments.toDouble()),
            duration: const Duration(milliseconds: 600),
            curve: Curves.easeOutCubic,
            builder: (context, lit, _) => AnimatedBuilder(
              animation: _c,
              builder: (context, _) => CustomPaint(
                painter: _RingPainter(
                  lit: lit,
                  color: color ?? widget.color,
                  swell: Curves.easeInOut.transform(_c.value),
                ),
                child: child,
              ),
            ),
          ),
          child: Center(child: widget.child),
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter({required this.lit, required this.color, required this.swell});
  final double lit;
  final Color color;
  final double swell;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final stroke = size.width * 0.075;
    final r = size.width / 2 - stroke / 2 - 4;

    // Soft halo behind the face of the ring.
    final halo = r - stroke * 0.2;
    canvas.drawCircle(c, halo * (0.92 + 0.05 * swell), Paint()..color = color.withValues(alpha: 0.10 + 0.05 * swell));
    canvas.drawCircle(c, halo * 0.78, Paint()..color = Pal.paper);

    const sweepTotal = math.pi * 1.5;
    const gap = 0.16;
    final seg = (sweepTotal - gap * 3) / 4;
    final start0 = math.pi * 0.75;
    final rect = Rect.fromCircle(center: c, radius: r);
    for (var i = 0; i < 4; i++) {
      final start = start0 + i * (seg + gap);
      final fill = (lit - i).clamp(0.0, 1.0);
      final track = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.round
        ..color = Pal.line;
      canvas.drawArc(rect, start, seg, false, track);
      if (fill > 0) {
        canvas.drawArc(rect, start, seg * fill, false, track..color = color);
      }
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) => old.lit != lit || old.color != color || old.swell != swell;
}
