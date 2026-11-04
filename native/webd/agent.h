/* The chat agent: talks to the Claude Messages API and shows the conversation as a document. */
#ifndef WEBD_AGENT_H
#define WEBD_AGENT_H

typedef struct {
	const char *api_key;           /* NULL: there isn't one, say how to add it */
	const char *api_base;
	const char *model;
} agent_config;

void agent_main(const agent_config *cfg);

#endif
