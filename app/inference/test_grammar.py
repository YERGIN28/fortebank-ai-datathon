"""CPU grammar tests with a character tokenizer, no weights or user input."""
import json
import unittest
from .grammar import JsonTokenGrammar


class Tokenizer:
    eos_token_id = 0
    def __call__(self, texts, **kwargs):
        return {'input_ids': [[ord(c) + 1 for c in text] for text in texts]}


class GrammarTests(unittest.TestCase):
    def consume(self, grammar, text):
        prefix = []
        for token in (ord(c) + 1 for c in text):
            self.assertIn(token, grammar.allowed_tokens(prefix))
            prefix.append(token)
        return grammar.allowed_tokens(prefix)

    def payload(self, count=1, **changes):
        row = {'s':0,'e':1,'a':'cash_transfer','o':'banknote','r':['cashier','customer']}
        row.update(changes)
        return json.dumps({'human_visible':True,'events':[row]*count},separators=(',',':'))

    def test_empty_and_two_events_are_valid(self):
        grammar = JsonTokenGrammar(Tokenizer(),2,'events')
        for text in ('{"human_visible":false,"events":[]}',
                     '{"human_visible":null,"events":[]}',self.payload(1),self.payload(2)):
            self.assertEqual(self.consume(grammar,text),[0])

    def test_third_event_and_invalid_enums_are_impossible(self):
        grammar = JsonTokenGrammar(Tokenizer(),2,'events')
        for text in (self.payload(3),self.payload(a='invented_action'),self.payload(o='invented_object'),
                     self.payload(r=['person_42']),self.payload(s=True),self.payload(s=-1),
                     self.payload(s=1,e=0),self.payload(e=2)):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                self.consume(grammar,text)

    def test_no_events_when_presence_false(self):
        grammar = JsonTokenGrammar(Tokenizer(),2,'events')
        text = self.payload().replace('true','false')
        with self.assertRaises(AssertionError): self.consume(grammar,text)

    def test_conditions_have_only_valid_states_and_frame_indexes(self):
        grammar = JsonTokenGrammar(Tokenizer(),3,('first','second'))
        text='{"first":{"state":"observed","frames":[0,2]},"second":{"state":"unclear","frames":[]}}'
        self.assertEqual(self.consume(grammar,text),[0])
        for invalid in (text.replace('observed','yes'),text.replace('[0,2]','[3]'),
                        text.replace('[0,2]','[2,0]'),text.replace('[0,2]','[]')):
            with self.assertRaises(AssertionError): self.consume(grammar,invalid)

    def test_object_and_relevance_schema(self):
        for schema,text in (('object','{"object_kind":"none"}'),('relevance','{"relevant":null}')):
            self.assertEqual(self.consume(JsonTokenGrammar(Tokenizer(),1,schema),text),[0])

    def test_invalid_frame_counts_rejected(self):
        for count in (0,17):
            with self.assertRaises(ValueError): JsonTokenGrammar(Tokenizer(),count,'events')
        with self.assertRaises(ValueError): JsonTokenGrammar(Tokenizer(),7,('condition',))


if __name__ == '__main__': unittest.main()
