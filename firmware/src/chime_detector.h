// Bell detector for the board. A port of strike_candidates() and strike_scores()
// in tools/chime.py: same frames, bands and checks, so a model trained there
// behaves the same here. Plain C++ so it can also be tested on a computer.
#pragma once

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <algorithm>

#include "chime_model.h"

class ChimeDetector {
 public:
  static const int FRAME = 1024;
  static const int HOP = 512;
  static const int RATE = 16000;
  static const int WINDOW = RATE / HOP;  // about 1 second of the fade
  static const int HALF = WINDOW / 2;
  static const int PRE = 6;   // frames before the strike: the "before" level
  static const int RISE = 3;  // frames the strike may take to peak
  static const int MIN_FADE_FRAMES = 8;
  static const int EARLY_FROM = 6, EARLY_TO = 9;  // frames after the strike
  static const int HISTORY = PRE + WINDOW;

  ChimeDetector() {
    for (int i = 0; i < FRAME; i++) hann_[i] = 0.5f - 0.5f * cosf(2 * M_PI * i / (FRAME - 1));
    for (int i = 0; i < FRAME / 2; i++) {
      twiddleRe_[i] = cosf(2 * M_PI * i / FRAME);
      twiddleIm_[i] = -sinf(2 * M_PI * i / FRAME);
    }
  }

  // The best recent bell-like sound, for /status: why it did or didn't count.
  struct Strike {
    float ageSeconds, level, purity, attack, fade, wobble, overtone, earlyDrop;
    bool passed;
  };

  bool lastStrike(Strike *out) const {
    if (!hasStrike_) return false;
    *out = strike_;
    out->ageSeconds = (frames_ - 1 - strikeFrame_) * (float)HOP / RATE;
    return true;
  }

  // Feed samples in order. Returns true when a ring ended in this block. endTime,
  // if set, gets the time it ended, in seconds from the first sample.
  bool feed(const int16_t *samples, size_t count, float *endTime = nullptr) {
    bool rang = false;
    for (size_t i = 0; i < count; i++) {
      pcm_[filled_++] = samples[i] / 32768.0f;
      if (filled_ < FRAME) continue;
      if (frame(endTime)) rang = true;
      memmove(pcm_, pcm_ + HOP, (FRAME - HOP) * sizeof(float));
      filled_ = FRAME - HOP;
    }
    return rang;
  }

 private:
  float pcm_[FRAME];
  int filled_ = 0;
  float hann_[FRAME], twiddleRe_[FRAME / 2], twiddleIm_[FRAME / 2];
  float re_[FRAME], im_[FRAME];
  // Ring buffers of per-frame values. Sums stay in double, as numpy's do.
  double tone_[HISTORY] = {}, overtone_[HISTORY] = {}, total_[HISTORY] = {};
  float db_[HISTORY] = {};
  long frames_ = 0;
  long lastHit_ = -1000000;
  Strike strike_ = {};
  long strikeFrame_ = 0;
  bool hasStrike_ = false;

  void fft() {
    for (int i = 1, j = 0; i < FRAME; i++) {
      int bit = FRAME >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        std::swap(re_[i], re_[j]);
        std::swap(im_[i], im_[j]);
      }
    }
    for (int len = 2; len <= FRAME; len <<= 1) {
      int half = len / 2, step = FRAME / len;
      for (int i = 0; i < FRAME; i += len) {
        for (int k = 0; k < half; k++) {
          float wr = twiddleRe_[k * step], wi = twiddleIm_[k * step];
          float a = re_[i + k + half], b = im_[i + k + half];
          float tr = a * wr - b * wi, ti = a * wi + b * wr;
          re_[i + k + half] = re_[i + k] - tr;
          im_[i + k + half] = im_[i + k] - ti;
          re_[i + k] += tr;
          im_[i + k] += ti;
        }
      }
    }
  }

  // Oldest index 0: the value that many frames after the start of the history.
  int at(int age) const { return (frames_ - HISTORY + age + HISTORY * 2) % HISTORY; }

  bool frame(float *endTime) {
    for (int i = 0; i < FRAME; i++) {
      re_[i] = pcm_[i] * hann_[i];
      im_[i] = 0;
    }
    fft();

    double tone = 0, overtone = 0, total = 0;
    const double binHz = (double)RATE / FRAME;
    for (int b = 0; b <= FRAME / 2; b++) {
      double f = b * binHz;
      double power = (double)re_[b] * re_[b] + (double)im_[b] * im_[b];
      if (f >= 300.0 && f <= 6000.0) total += power;
      if (fabs(f - CHIME_TONE_HZ) <= CHIME_TONE_WIDTH_HZ) tone += power;
      for (int k = 2; k <= 3; k++) {
        if (fabs(f - CHIME_TONE_HZ * k) <= CHIME_TONE_WIDTH_HZ * k) overtone += power;
      }
    }

    int slot = frames_ % HISTORY;
    tone_[slot] = tone;
    overtone_[slot] = overtone;
    total_[slot] = std::max(total, 1e-12);
    db_[slot] = 10 * log10(tone + 1e-12);
    frames_++;
    if (frames_ < HISTORY) return false;

    if (!strike()) return false;
    long end = frames_ - 1;
    float t = (end * HOP + FRAME) / (float)RATE;
    if ((end - lastHit_) * HOP < CHIME_COOLDOWN_S * RATE) return false;
    lastHit_ = end;
    if (endTime) *endTime = t;
    return true;
  }

  // Would the strike that began one window ago pass? Index s is at(PRE).
  bool strike() {
    double peakTone = 0;
    float head = -1e9f;
    for (int i = 0; i < RISE; i++) {
      peakTone = std::max(peakTone, tone_[at(PRE + i)]);
      head = std::max(head, db_[at(PRE + i)]);
    }
    float pre[PRE];
    for (int i = 0; i < PRE; i++) pre[i] = db_[at(i)];
    std::sort(pre, pre + PRE);
    float before = (pre[PRE / 2 - 1] + pre[PRE / 2]) / 2;
    float attack = head - before;
    if (attack <= 0) return false;

    int peakAt = 0;
    for (int i = 1; i < WINDOW; i++) {
      if (db_[at(PRE + i)] > db_[at(PRE + peakAt)]) peakAt = i;
    }
    if (peakAt >= RISE) return false;

    // Fit a line to the part of the fade still above the noise.
    const float hopS = (float)HOP / RATE;
    double n = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (int i = RISE - 1; i < WINDOW; i++) {
      float y = db_[at(PRE + i)];
      if (y <= before + 6.0f) continue;
      double x = i * hopS;
      n++;
      sx += x;
      sy += y;
      sxx += x * x;
      sxy += x * y;
    }
    if (n < MIN_FADE_FRAMES) return false;
    double slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
    double intercept = (sy - slope * sx) / n;

    double residual = 0, mean = 0;
    for (int pass = 0; pass < 2; pass++) {
      for (int i = RISE - 1; i < WINDOW; i++) {
        float y = db_[at(PRE + i)];
        if (y <= before + 6.0f) continue;
        double r = y - (slope * i * hopS + intercept);
        if (pass == 0) mean += r / n;
        else residual += (r - mean) * (r - mean);
      }
    }
    double wobble = sqrt(residual / n);

    double toneSum = 0, overSum = 0, puritySum = 0;
    for (int i = 0; i < HALF; i++) {
      int a = at(PRE + i);
      toneSum += tone_[a];
      overSum += overtone_[a];
      puritySum += tone_[a] / total_[a];
    }
    double overtone = 10 * log10((overSum + 1e-12) / (toneSum + 1e-12));
    double purity = puritySum / HALF;

    float later = 0;
    for (int i = EARLY_FROM; i < EARLY_TO; i++) later += db_[at(PRE + i)];
    float earlyDrop = head - later / (EARLY_TO - EARLY_FROM);

    bool passed = earlyDrop >= CHIME_MIN_EARLY_DROP_DB && peakTone >= CHIME_MIN_LEVEL && attack >= CHIME_MIN_ATTACK_DB && slope >= CHIME_FADE_MIN_DB_S &&
                  slope <= CHIME_FADE_MAX_DB_S && wobble <= CHIME_MAX_WOBBLE_DB &&
                  overtone <= CHIME_MAX_OVERTONE_DB && purity > CHIME_THRESHOLD;
    // Keep the most bell-like sound of the last few seconds to report.
    bool stale = !hasStrike_ || (frames_ - 1 - strikeFrame_) * HOP > 3 * RATE;
    if (purity > 0.2 && (stale || purity >= strike_.purity)) {
      strike_ = {0, head, (float)purity, attack, (float)slope, (float)wobble, (float)overtone, earlyDrop, passed};
      strikeFrame_ = frames_ - 1;
      hasStrike_ = true;
    }
    return passed;
  }
};
