import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme.dart';

/// Smooth animated semicircle meter: 0 Safe → 3 Critical.
class PressureGauge extends StatelessWidget {
  final int pressure;
  final double height;
  const PressureGauge({super.key, required this.pressure, this.height = 170});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(end: pressure.toDouble()),
      duration: const Duration(milliseconds: 700),
      curve: Curves.easeOutCubic,
      builder: (context, v, _) {
        final color = Color.lerp(
            Pal.forPressure(v.floor()), Pal.forPressure((v.floor() + 1).clamp(0, 3)), v - v.floor())!;
        return Semantics(
          label: 'Scam pressure ${Pal.labelFor(pressure)}, level $pressure of 3',
          child: SizedBox(
            height: height,
            child: Stack(alignment: Alignment.bottomCenter, children: [
              Positioned.fill(child: CustomPaint(painter: _ArcPainter(v))),
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(Pal.labelFor(pressure),
                      style: TextStyle(fontSize: 28, fontWeight: FontWeight.w900, color: color)),
                  const Text('SCAM PRESSURE', style: TextStyle(fontSize: 15, color: Pal.dim, letterSpacing: 2)),
                ]),
              ),
            ]),
          ),
        );
      },
    );
  }
}

class _ArcPainter extends CustomPainter {
  final double value; // 0..3
  _ArcPainter(this.value);

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 22.0;
    final r = math.min(size.width / 2, size.height - 20) - stroke / 2;
    final center = Offset(size.width / 2, size.height - 20);
    final rect = Rect.fromCircle(center: center, radius: r);
    const sweepTotal = math.pi;
    final seg = sweepTotal / 4;
    // Background track in four zone colours (dimmed).
    for (var i = 0; i < 4; i++) {
      canvas.drawArc(
          rect,
          math.pi + i * seg + 0.02,
          seg - 0.04,
          false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = stroke
            ..color = Pal.forPressure(i).withValues(alpha: 0.22));
    }
    // Needle: value 0 → centre of first zone, 3 → centre of last.
    final ang = math.pi + seg / 2 + (value / 3) * (sweepTotal - seg);
    // Lit fill up to the needle.
    final fillEnd = ang - math.pi;
    for (var i = 0; i < 4; i++) {
      final start = i * seg;
      if (fillEnd <= start) break;
      final len = math.min(seg, fillEnd - start);
      canvas.drawArc(
          rect,
          math.pi + start + 0.02,
          math.max(0, len - 0.04),
          false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = stroke
            ..strokeCap = StrokeCap.butt
            ..color = Pal.forPressure(i));
    }
    final tip = center + Offset(math.cos(ang), math.sin(ang)) * (r - 8);
    canvas.drawLine(
        center,
        tip,
        Paint()
          ..color = Colors.white
          ..strokeWidth = 6
          ..strokeCap = StrokeCap.round);
    canvas.drawCircle(center, 10, Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(_ArcPainter old) => old.value != value;
}
