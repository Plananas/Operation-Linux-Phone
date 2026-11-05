#include "gemini.h"

#include <string.h>

#include "json.h"

static void set_string(json_val v, sb *out)
{
	out->n = 0;
	if (out->s)
		out->s[0] = '\0';
	json_string(v, out);
}

static int is_true(json_val v)
{
	return v.n == 4 && !memcmp(v.s, "true", 4);
}

static void add_call(gemini_reply *r, json_val fc)
{
	if (r->n_calls >= GEMINI_MAX_CALLS) {
		r->too_many_calls = 1;
		return;
	}
	gemini_call *c = &r->calls[r->n_calls++];
	json_val v;
	if (json_get(fc.s, fc.n, "name", &v))
		json_string(v, &c->name);
	if (json_get(fc.s, fc.n, "id", &v))
		json_string(v, &c->id);
	if (json_get(fc.s, fc.n, "args", &v))
		sb_add(&c->args, v.s, v.n);
}

/* Parts go back exactly as they came: that's how a thought signature, wherever it sits, gets returned. The one
 * exception is empty text with nothing attached, which is only a stream's way of finishing. */
static void read_part(gemini_reply *r, json_val part)
{
	json_val v, flag;
	if (json_get(part.s, part.n, "functionCall", &v)) {
		add_call(r, v);
	} else if (json_get(part.s, part.n, "text", &v)) {
		const int thought = json_get(part.s, part.n, "thought", &flag) && is_true(flag);
		if (v.n == 2 && !thought && !json_get(part.s, part.n, "thoughtSignature", &flag))
			return;
		if (!thought)
			json_string(v, &r->text);
	}
	if (r->parts.n)
		sb_adds(&r->parts, ",");
	sb_add(&r->parts, part.s, part.n);
}

void gemini_read_chunk(const char *js, size_t n, gemini_reply *r)
{
	json_val v, candidate, part;
	if (json_get(js, n, "error.message", &v))
		set_string(v, &r->error);
	if (json_get(js, n, "promptFeedback.blockReason", &v))
		r->blocked = 1;
	size_t at = 0;
	if (!json_get(js, n, "candidates", &v) || !json_each(v, &at, &candidate))
		return;
	if (json_get(candidate.s, candidate.n, "finishReason", &v))
		set_string(v, &r->finish);
	if (!json_get(candidate.s, candidate.n, "content.parts", &v))
		return;
	at = 0;
	while (json_each(v, &at, &part))
		read_part(r, part);
}

static int finished_with(const gemini_reply *r, const char *reason)
{
	return r->finish.s && !strcmp(r->finish.s, reason);
}

gemini_outcome gemini_outcome_of(const gemini_reply *r)
{
	static const char *const DECLINED[] = { "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII" };
	for (size_t i = 0; i < sizeof(DECLINED) / sizeof(DECLINED[0]); i++)
		if (finished_with(r, DECLINED[i]))
			return GEMINI_DECLINED;
	if (r->blocked)
		return GEMINI_DECLINED;
	if (r->too_many_calls)
		return GEMINI_FAILED;
	if (finished_with(r, "STOP") && r->n_calls)
		return GEMINI_CALLS;
	if (finished_with(r, "STOP") && r->text.n)
		return GEMINI_DONE;
	/* Cut off in the middle of asking for a tool, or before saying anything, there's nothing to keep: a call that
	 * has no answer would make the API refuse the rest of the conversation. */
	if (finished_with(r, "MAX_TOKENS") && r->text.n && !r->n_calls)
		return GEMINI_CUT_OFF;
	return GEMINI_FAILED;
}

void gemini_reply_clear(gemini_reply *r)
{
	sb_free(&r->text);
	sb_free(&r->parts);
	sb_free(&r->finish);
	sb_free(&r->error);
	for (int i = 0; i < r->n_calls; i++) {
		sb_free(&r->calls[i].name);
		sb_free(&r->calls[i].id);
		sb_free(&r->calls[i].args);
	}
	memset(r, 0, sizeof(*r));
}

static void next_content(sb *contents)
{
	if (contents->n)
		sb_adds(contents, ",");
}

void gemini_add_user(sb *contents, const char *text, size_t n)
{
	next_content(contents);
	sb_adds(contents, "{\"role\":\"user\",\"parts\":[{\"text\":");
	json_quote(contents, text, n);
	sb_adds(contents, "}]}");
}

void gemini_add_model(sb *contents, const gemini_reply *r)
{
	next_content(contents);
	sb_adds(contents, "{\"role\":\"model\",\"parts\":[");
	sb_add(contents, r->parts.s, r->parts.n);
	sb_adds(contents, "]}");
}

void gemini_add_result(sb *results, const gemini_call *call, const char *text, size_t n, int ok)
{
	if (results->n)
		sb_adds(results, ",");
	sb_adds(results, "{\"functionResponse\":{");
	if (call->id.n) {
		sb_adds(results, "\"id\":");
		json_quote(results, call->id.s, call->id.n);
		sb_adds(results, ",");
	}
	sb_adds(results, "\"name\":");
	json_quote(results, call->name.s ? call->name.s : "", call->name.n);
	sb_adds(results, ok ? ",\"response\":{\"result\":" : ",\"response\":{\"error\":");
	json_quote(results, text ? text : "", n);
	sb_adds(results, "}}}");
}

void gemini_add_results(sb *contents, const sb *results)
{
	next_content(contents);
	sb_adds(contents, "{\"role\":\"user\",\"parts\":[");
	sb_add(contents, results->s, results->n);
	sb_adds(contents, "]}");
}

int gemini_forget_turns(sb *contents, size_t *starts, int n, int cap, size_t max)
{
	int first = n >= cap ? n - cap + 1 : 0;
	while (first < n - 1 && contents->n - starts[first] > max)
		first++;
	if (first <= 0 || first >= n)
		return n;
	const size_t cut = starts[first] + 1;  /* and the comma in front of it */
	contents->n -= cut;
	memmove(contents->s, contents->s + cut, contents->n);
	contents->s[contents->n] = '\0';
	for (int i = first + 1; i < n; i++)
		starts[i - first] = starts[i] - cut;
	starts[0] = 0;
	return n - first;
}

void gemini_body(sb *body, const char *system, const char *tools, const sb *contents)
{
	sb_adds(body, "{\"systemInstruction\":{\"parts\":[{\"text\":");
	json_quote(body, system, strlen(system));
	sb_adds(body, "}]},\"tools\":");
	sb_adds(body, tools);
	sb_adds(body, ",\"generationConfig\":{\"maxOutputTokens\":4000},\"contents\":[");
	sb_add(body, contents->s, contents->n);
	sb_adds(body, "]}");
}
