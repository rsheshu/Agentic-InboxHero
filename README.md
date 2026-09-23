https://github.com/rsheshu/Agentic-InboxHero

**1. What did you refuse to automate? Name one message your system deliberately does not handle on its own, and explain why you drew the line there.**

   Any message which violates the security aspect. e.g. sharing passwords,key credential in an unsecured channel. m008 where the send asking for passwords and urls for need the staging servers.
   This is a credential-bearing request and the system must be designed to refuse such unsecured requests and respond with suggestion to use approved secured channel.The system is just an automation
   for inbox email triage.
   
**2. Where does untrusted text enter your system? Describe the boundary between text your system reads and instructions it follows, as a property of your architecture rather than a line in a prompt. Name what an attacker would have to defeat to make your system act on their behalf.**

Inbox.json is the place for untrusted text entry to the system like phishing messages,validations request message etc. The key architectural property creates the boundary of safeguard
- All inbound message bodies are treated as data, not instructions. The system does not let a message directly trigger side effects.
- The only operations that can produce action are gated and policy-driven:
   - retrieve_and_draft() builds a draft from thread context
   - action_gate() approves or rejects actions before irreversible effects
   - irreversible operations are limited to send/delete and are not allowed without the gate
  The execution layer of response is not influenced by the message request rather hardened by the policy i..e gated action defined around the messages response to refuse any unsecured ask around credential,sharing sensitive information which is well defined in the policy . Attacker needs to by pass different layers of the pipeline
 - Preference and routing : message should not be in phising and unsecured emailId in nature
 - Message - Data boundary : Parse message content not as request
 - Policy checks           : Refuse certain pre-defined responses types
 - Irreversible gate check  : The human in the loop for the approval to send 

**3. Who is accountable when it sends the wrong thing? If a message sent in the owner’s name is badly worded, factually wrong, or sent to the wrong person, who is answerable, and how does your system help trace back the failure?**

- The human is the only responsible person as he has approved the final  irreversible gate for the message to be sent. The important architectural point is that the system does not treat the email as “free-form magic”; it records why it decided to send, what thread it used, and what policy gate it passed.The system’s main value is not to avoid human responsibility; it is to make the mistake auditable:
- The message tracking which should happen . the original message in inbox.json -> the thread it came from ->  the route decision -> the draft body ->  the evidence message IDs used - > the final outbox/trace entry
   
**4. Name your own machinery. Point to the parts of your code that play the roles of a framework’s Agents, Tasks, Crew and router. Name one thing a framework would have given you that you built yourself, and say whether using one here would have helped or hurt, and why.See the capabilities.md file for details**
 
 - I would call it the InboxHero triage pipeline. It is a small, explicit orchestration layer rather than a full agent framework, and the pieces map to framework concepts. I found it struggling to retrofit in the agent framework but still i tried to embed to get the best of both the worlds. This framework offer only an added advantage for quick POCs and for simple analysis tasks rather a triaging entity
 -  It would likely have helped a little for scale, but hurt for this specific project.
       - Why it would hurt:
         - The logic is small and explicit
         - The trust boundary matters more than framework abstraction
         - The safety model would  deterministic & clearer in plain code than in a framework-managed workflow
         - 
       - Why it would help:
         -   more standard observability
         -   easier extension if the project grows to many tools and agents
           
- For this inbox project, the custom pipeline is actually a net win because it keeps the system readable, auditable, and easy to reason about. The trust boundary and approval gate are more important than framework elegance, and that is exactly the kind of design the project is trying to preserve.
