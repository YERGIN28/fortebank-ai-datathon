"""Small token tries constrain JSON syntax, enums and sampled-frame indexes.

This guarantees format only, never the truth of a visual claim. No additional
models, network libraries or grammar packages are required.
"""
import itertools
import json

from .schemas import ACTOR_ROLES, OBJECT_KINDS, OBSERVATION_TYPES

END = -1


def _json(value):
    return json.dumps(value, separators=(',', ':'))


class JsonTokenGrammar:
    def __init__(self, tokenizer, frame_count, schema):
        if not 1 <= frame_count <= 16:
            raise ValueError('Constrained output supports 1..16 sampled frames')
        self.tokenizer = tokenizer
        eos = tokenizer.eos_token_id
        if type(eos) is not int:
            raise ValueError('Tokenizer requires one EOS token')
        self.eos = {eos: {END: 'done'}}
        self.states = {}
        if schema == 'events':
            self.start = self.trie([
                ('{"human_visible":false,"events":[]}', 'done'),
                ('{"human_visible":true,"events":[', 'body'),
                ('{"human_visible":null,"events":[', 'body'),
            ])
            roles = [[role] for role in ACTOR_ROLES] + [['cashier', 'customer']]
            rows = [(_json({'s': start, 'e': end, 'a': action, 'o': kind, 'r': role}), 'row')
                    for start in range(frame_count) for end in range(start, frame_count)
                    for action in OBSERVATION_TYPES for kind in OBJECT_KINDS for role in roles]
            self.states['row_start'] = self.trie(rows)
            close = self.trie([(']}', 'done')])
            row_root = self.states['row_start']
            if set(close) & set(row_root):
                raise ValueError('Ambiguous tokenizer boundary')
            self.states['body'] = {**close, **row_root}
            comma = self.trie([(',', 'row_start')])
            if set(close) & set(comma):
                raise ValueError('Ambiguous separator boundary')
            self.after_first = {**close, **comma}
            self.after_second = close
        elif schema == 'object':
            self.start = self.trie([(_json({'object_kind': kind}), 'done') for kind in OBJECT_KINDS])
        elif schema == 'relevance':
            self.start = self.trie([(_json({'relevant': value}), 'done') for value in (True, False, None)])
        elif isinstance(schema, tuple) and schema:
            if frame_count > 6:
                raise ValueError('Condition grammar supports at most six context frames')
            self.start = self.trie([('{', 'field_0')])
            subsets = [list(indexes) for count in range(frame_count + 1)
                       for indexes in itertools.combinations(range(frame_count), count)]
            for index, name in enumerate(schema):
                next_state = 'field_' + str(index + 1) if index + 1 < len(schema) else 'finish'
                choices = []
                for state in ('observed', 'refuted', 'unclear'):
                    for indexes in subsets:
                        # Unsupported evidence is represented by unclear, never observed.
                        if not indexes and state != 'unclear':
                            continue
                        text = (',' if index else '') + _json(name) + ':' + _json({'state':state,'frames':indexes})
                        choices.append((text, next_state))
                self.states['field_' + str(index)] = self.trie(choices)
            self.states['finish'] = self.trie([('}', 'done')])
        else:
            raise ValueError('Unknown output grammar')

    def trie(self, choices):
        root = {}
        texts = [text for text, _ in choices]
        tokenized = self.tokenizer(texts, add_special_tokens=False,
                                   return_attention_mask=False)['input_ids']
        for tokens, (_, target) in zip(tokenized, choices):
            node = root
            for token in tokens:
                if END in node:
                    raise ValueError('Ambiguous terminal prefix')
                node = node.setdefault(token, {})
            if node:
                raise ValueError('Ambiguous output prefix')
            node[END] = target
        return root

    def allowed_tokens(self, generated):
        node = self.start
        rows = 0
        for token in generated:
            if token not in node or token == END:
                raise ValueError('Generated token outside output grammar')
            node = node[token]
            target = node.get(END)
            if target == 'row':
                rows += 1
                node = self.after_first if rows == 1 else self.after_second
            elif target == 'done':
                node = self.eos
            elif target is not None:
                node = self.states[target]
        return list(node)
