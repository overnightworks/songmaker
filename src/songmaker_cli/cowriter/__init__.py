"""What songmaker brings to a co-writer turn that no provider can know.

The provider layer runs the turn; this package holds the four things that are
songmaker's own: which route a musician's turn takes and whose permissions it
acts under (``routing``), the tools it may call and how they execute
(``tools``), the conversation history it is given (``history``), and the MCP
server declaration Claude's CLI attaches (``mcp_spec``).
"""
