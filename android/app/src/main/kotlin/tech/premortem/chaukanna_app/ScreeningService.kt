package tech.premortem.chaukanna_app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.telecom.Call
import android.telecom.CallScreeningService
import org.json.JSONArray
import org.json.JSONObject

/**
 * Looks at every incoming call before it rings. This is the one thing Android lets an app
 * do to ordinary calls reliably: it sees the number, so a number on the shared scam list is
 * rejected, and one from a country that scam calls to India keep coming from is flagged.
 * It does not hear the call.
 */
class ScreeningService : CallScreeningService() {
    override fun onScreenCall(details: Call.Details) {
        val incoming = Build.VERSION.SDK_INT < 29 || details.callDirection == Call.Details.DIRECTION_INCOMING
        val number = details.handle?.schemeSpecificPart.orEmpty()
        if (!incoming || number.isEmpty()) {
            respondToCall(details, CallResponse.Builder().build())
            return
        }
        val verdict = ScamLists.check(this, number)
        val response = CallResponse.Builder()
        when (verdict.kind) {
            ScamLists.Kind.KNOWN -> response.setDisallowCall(true).setRejectCall(true).setSkipCallLog(false)
            else -> {}
        }
        respondToCall(details, response.build())
        if (verdict.kind != ScamLists.Kind.CLEAN) {
            BlockLog.add(this, number, verdict)
            alert(number, verdict)
        }
    }

    private fun alert(number: String, v: ScamLists.Verdict) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Scam call alerts", NotificationManager.IMPORTANCE_HIGH)
            )
        }
        val open = PendingIntent.getActivity(
            this,
            1,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val (title, text) = when (v.kind) {
            ScamLists.Kind.KNOWN -> "Blocked a known scam call" to "$number is on the shared scam list. It did not ring."
            else -> "Careful: call from ${v.note}" to "$number is from a country that many scam calls to India come from."
        }
        val b = if (Build.VERSION.SDK_INT >= 26) android.app.Notification.Builder(this, CHANNEL_ID)
        else @Suppress("DEPRECATION") android.app.Notification.Builder(this)
        nm.notify(
            (System.currentTimeMillis() % 100000).toInt(),
            b.setContentTitle(title)
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build(),
        )
    }

    companion object {
        private const val CHANNEL_ID = "chaukanna_alerts"
    }
}

/** The shared scam list and risky country codes, bundled with the app. */
object ScamLists {
    enum class Kind { CLEAN, KNOWN, RISKY_COUNTRY }

    data class Verdict(val kind: Kind, val note: String = "")

    private var known: Set<String>? = null
    private var codes: List<Pair<String, String>>? = null

    private fun read(ctx: Context, name: String): JSONObject? = try {
        ctx.assets.open("flutter_assets/assets/scam/$name").bufferedReader().use { JSONObject(it.readText()) }
    } catch (_: Exception) {
        null
    }

    /** Digits only; a bare 10-digit or 0-prefixed Indian number becomes 91 + number. */
    fun normalise(raw: String): String {
        var d = raw.filter { it.isDigit() }
        if (d.length == 11 && d.startsWith("0")) d = d.substring(1)
        if (d.length == 10) d = "91$d"
        return d
    }

    @Synchronized
    fun check(ctx: Context, raw: String): Verdict {
        if (known == null) {
            val arr: JSONArray = read(ctx, "scam_numbers.json")?.optJSONArray("numbers") ?: JSONArray()
            known = (0 until arr.length()).map { normalise(arr.getJSONObject(it).optString("number")) }.toSet()
            val obj = read(ctx, "risky_country_codes.json")?.optJSONObject("codes")
            codes = obj?.keys()?.asSequence()?.map { it to obj.optString(it) }
                ?.sortedByDescending { it.first.length }?.toList() ?: emptyList()
        }
        val n = normalise(raw)
        if (n in known!!) return Verdict(Kind.KNOWN)
        if (raw.trim().startsWith("+") || raw.trim().startsWith("00")) {
            val e164 = "+" + raw.filter { it.isDigit() }.removePrefix("00")
            codes!!.firstOrNull { e164.startsWith(it.first) }?.let { return Verdict(Kind.RISKY_COUNTRY, it.second) }
        }
        return Verdict(Kind.CLEAN)
    }
}

/** The last 30 numbers screened, kept for the app to show. */
object BlockLog {
    private const val PREFS = "chaukanna_guard"
    private const val KEY = "screened"

    @Synchronized
    fun add(ctx: Context, number: String, v: ScamLists.Verdict) {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val old = try { JSONArray(prefs.getString(KEY, "[]")) } catch (_: Exception) { JSONArray() }
        val entry = JSONObject()
            .put("number", number)
            .put("kind", if (v.kind == ScamLists.Kind.KNOWN) "blocked" else "flagged")
            .put("note", v.note)
            .put("at", System.currentTimeMillis())
        val out = JSONArray().put(entry)
        for (i in 0 until minOf(old.length(), 29)) out.put(old.get(i))
        prefs.edit().putString(KEY, out.toString()).apply()
    }

    fun read(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "[]") ?: "[]"
}
